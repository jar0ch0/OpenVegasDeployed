"""Supabase Auth for CLI token issuance and refresh."""

from supabase import create_client, Client

from openvegas.config import load_config, save_session, clear_session


class AuthError(Exception):
    pass


class SupabaseAuth:
    def __init__(self):
        config = load_config()
        url = config.get("supabase_url", "")
        key = config.get("supabase_anon_key", "")
        if not url or not key:
            raise AuthError(
                "Supabase not configured. Run: openvegas config set supabase_url <url>"
            )
        self.client: Client = create_client(url, key)

    def login_with_email(self, email: str, password: str) -> dict:
        resp = self.client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        save_session(resp.session.access_token, resp.session.refresh_token)
        return {"user_id": resp.user.id, "email": resp.user.email}

    def login_with_otp(self, email: str) -> None:
        self.client.auth.sign_in_with_otp({"email": email})

    def signup(self, email: str, password: str) -> dict:
        resp = self.client.auth.sign_up({
            "email": email,
            "password": password,
        })
        if resp.session:
            save_session(resp.session.access_token, resp.session.refresh_token)
        return {"user_id": resp.user.id, "email": resp.user.email}

    def refresh_token(self) -> str:
        from openvegas.config import get_session
        session = get_session()
        refresh = session.get("refresh_token", "")
        if not refresh:
            raise AuthError("No refresh token. Please login again.")
        resp = self.client.auth.refresh_session(refresh)
        save_session(resp.session.access_token, resp.session.refresh_token)
        return resp.session.access_token

    def logout(self) -> None:
        try:
            self.client.auth.sign_out()
        except Exception:
            pass
        clear_session()
