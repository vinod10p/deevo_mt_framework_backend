"""FastAPI application entry point for deevo_mt_framework_backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtf.audit.api import router as audit_router
from mtf.audit.middleware import AuditRequestIdMiddleware
from mtf.auth.api import router as auth_router
from mtf.nav.api import router as nav_router
from mtf.rpt.api import router as rpt_router
from mtf.shared.config import get_settings
from mtf.tenant.api import router as tenant_router
from mtf.tenant.api.tenant_account_portal import router as tenant_account_portal_router
from mtf.txn.api import router as txn_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    # Validated in Settings: exact origins; production = https only, never "*".
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # Auth is a Bearer header (no cookies); clients may send other harmless headers.
    allow_headers=["*"],
    # Let browsers read the wait time on 429 from /api/auth/login.
    expose_headers=["Retry-After"],
)
app.add_middleware(AuditRequestIdMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    """Load balancer / probe endpoint — no authentication."""
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api/auth")
app.include_router(tenant_router, prefix="/api/tenant")
app.include_router(tenant_account_portal_router, prefix="/api/account")
app.include_router(audit_router, prefix="/api/audit")
app.include_router(rpt_router, prefix="/api")
app.include_router(txn_router, prefix="/api")
app.include_router(nav_router, prefix="/api")

from mtf.tenant.api.tenant import mailbox_oauth_callback
app.get("/api/v1/mailboxes/callback")(mailbox_oauth_callback)



if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
