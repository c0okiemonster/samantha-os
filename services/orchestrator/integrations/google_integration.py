"""
Samantha OS — Google Integration
Gmail, Google Calendar, and Contacts via OAuth2.

Setup:
  1. Create a project at https://console.cloud.google.com
  2. Enable Gmail API, Calendar API, People API
  3. Create OAuth 2.0 credentials (Desktop app)
  4. Download client_secret.json → config/google_credentials.json
  5. Set GOOGLE_CREDENTIALS_FILE in .env

First run will open a browser for OAuth consent.
Token is cached at config/google_token.json.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from integrations import BaseIntegration, IntegrationAction, IntegrationStatus

logger = logging.getLogger("samantha.google")

# Scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/contacts.readonly",
]


class GoogleIntegration(BaseIntegration):
    name = "google"
    display_name = "Google (Gmail + Calendar)"
    description = "Read/send emails, manage calendar events, access contacts"
    icon = "📧"
    requires_auth = True

    def __init__(self):
        super().__init__()
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expiry: datetime | None = None
        self.client_id: str = ""
        self.client_secret: str = ""
        self._credentials_file: str = ""
        self._token_file: str = ""

    async def initialize(self, config: dict) -> bool:
        self._credentials_file = config.get("credentials_file", "config/google_credentials.json")
        self._token_file = config.get("token_file", "config/google_token.json")

        # Load client credentials
        if not os.path.exists(self._credentials_file):
            logger.warning(f"Google credentials file not found: {self._credentials_file}")
            logger.info("Follow setup instructions in config/README-google.md")
            return False

        with open(self._credentials_file) as f:
            creds = json.load(f)
            installed = creds.get("installed", creds.get("web", {}))
            self.client_id = installed.get("client_id", "")
            self.client_secret = installed.get("client_secret", "")

        # Load cached token
        if os.path.exists(self._token_file):
            with open(self._token_file) as f:
                token_data = json.load(f)
                self.access_token = token_data.get("access_token")
                self.refresh_token = token_data.get("refresh_token")
                expiry = token_data.get("expiry")
                if expiry:
                    self.token_expiry = datetime.fromisoformat(expiry)

            # Try refreshing if expired
            if self.token_expiry and datetime.now() > self.token_expiry:
                await self._refresh_access_token()

            if self.access_token:
                logger.info("Google: using cached token")
                return True

        # No valid token — need OAuth flow
        logger.info("Google: OAuth required. Run the setup script:")
        logger.info(f"  python -m integrations.google_oauth --credentials {self._credentials_file}")
        return False

    async def _refresh_access_token(self):
        if not self.refresh_token:
            return
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post("https://oauth2.googleapis.com/token", data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                })
                data = resp.json()
                self.access_token = data.get("access_token")
                expires_in = data.get("expires_in", 3600)
                self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                self._save_token()
                logger.info("Google: token refreshed")
        except Exception as e:
            logger.error(f"Google token refresh failed: {e}")

    def _save_token(self):
        with open(self._token_file, "w") as f:
            json.dump({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expiry": self.token_expiry.isoformat() if self.token_expiry else None,
            }, f)

    async def _api(self, method: str, url: str, **kwargs) -> dict:
        """Make an authenticated Google API call."""
        if self.token_expiry and datetime.now() > self.token_expiry:
            await self._refresh_access_token()

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="check_email",
                description="Check recent emails in Gmail",
                keywords=["email", "mail", "inbox", "messages", "unread"],
                parameters=["count", "query"],
                examples=["Check my email", "Any new emails?", "Do I have unread messages?"],
            ),
            IntegrationAction(
                name="send_email",
                description="Send an email via Gmail",
                keywords=["send email", "write email", "email to", "mail to", "compose"],
                parameters=["to", "subject", "body"],
                examples=["Send an email to john@example.com about the meeting"],
            ),
            IntegrationAction(
                name="check_calendar",
                description="Check upcoming calendar events",
                keywords=["calendar", "schedule", "meetings", "events", "what's next", "agenda"],
                parameters=["days_ahead"],
                examples=["What's on my calendar?", "Any meetings today?", "What's my schedule this week?"],
            ),
            IntegrationAction(
                name="create_event",
                description="Create a calendar event",
                keywords=["schedule", "book", "create event", "add to calendar", "set up meeting"],
                parameters=["title", "start", "end", "description", "attendees"],
                examples=["Schedule a meeting tomorrow at 2pm", "Add lunch with Sarah to my calendar"],
            ),
            IntegrationAction(
                name="search_contacts",
                description="Search Google contacts",
                keywords=["contact", "phone number", "email address", "find person"],
                parameters=["query"],
                examples=["What's Sarah's email?", "Find John's phone number"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        handlers = {
            "check_email": self._check_email,
            "send_email": self._send_email,
            "check_calendar": self._check_calendar,
            "create_event": self._create_event,
            "search_contacts": self._search_contacts,
        }
        handler = handlers.get(action_name)
        if not handler:
            return {"error": f"Unknown action: {action_name}"}
        return await handler(params)

    async def _check_email(self, params: dict) -> dict:
        count = params.get("count", 5)
        query = params.get("query", "is:unread")
        try:
            data = await self._api("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages", params={
                "maxResults": count, "q": query,
            })
            messages = data.get("messages", [])
            results = []
            for msg_ref in messages[:count]:
                msg = await self._api("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_ref['id']}", params={
                    "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"],
                })
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                results.append({
                    "id": msg_ref["id"],
                    "from": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                })
            return {"emails": results, "total": data.get("resultSizeEstimate", 0)}
        except Exception as e:
            return {"error": str(e)}

    async def _send_email(self, params: dict) -> dict:
        import base64
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to:
            return {"error": "No recipient specified"}

        raw_message = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        encoded = base64.urlsafe_b64encode(raw_message.encode()).decode()

        try:
            result = await self._api("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={
                "raw": encoded,
            })
            return {"sent": True, "id": result.get("id"), "to": to, "subject": subject}
        except Exception as e:
            return {"error": str(e)}

    async def _check_calendar(self, params: dict) -> dict:
        days = params.get("days_ahead", 1)
        now = datetime.utcnow()
        end = now + timedelta(days=days)
        try:
            data = await self._api("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events", params={
                "timeMin": now.isoformat() + "Z",
                "timeMax": end.isoformat() + "Z",
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 20,
            })
            events = []
            for ev in data.get("items", []):
                start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
                events.append({
                    "title": ev.get("summary", "(no title)"),
                    "start": start,
                    "end": ev.get("end", {}).get("dateTime", ""),
                    "location": ev.get("location", ""),
                    "attendees": [a.get("email") for a in ev.get("attendees", [])],
                })
            return {"events": events, "period": f"next {days} day(s)"}
        except Exception as e:
            return {"error": str(e)}

    async def _create_event(self, params: dict) -> dict:
        title = params.get("title", "New Event")
        start = params.get("start", "")
        end = params.get("end", "")
        desc = params.get("description", "")
        attendees = params.get("attendees", [])

        if not start:
            return {"error": "No start time specified"}

        event_body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start, "timeZone": "Europe/Stockholm"},
            "end": {"dateTime": end or start, "timeZone": "Europe/Stockholm"},
        }
        if desc:
            event_body["description"] = desc
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]

        try:
            result = await self._api("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", json=event_body)
            return {"created": True, "title": title, "link": result.get("htmlLink", "")}
        except Exception as e:
            return {"error": str(e)}

    async def _search_contacts(self, params: dict) -> dict:
        query = params.get("query", "")
        try:
            data = await self._api("GET", "https://people.googleapis.com/v1/people:searchContacts", params={
                "query": query, "readMask": "names,emailAddresses,phoneNumbers", "pageSize": 5,
            })
            contacts = []
            for result in data.get("results", []):
                person = result.get("person", {})
                names = person.get("names", [{}])
                emails = person.get("emailAddresses", [])
                phones = person.get("phoneNumbers", [])
                contacts.append({
                    "name": names[0].get("displayName", "Unknown") if names else "Unknown",
                    "emails": [e.get("value") for e in emails],
                    "phones": [p.get("value") for p in phones],
                })
            return {"contacts": contacts}
        except Exception as e:
            return {"error": str(e)}

    async def get_proactive_updates(self) -> list[dict] | None:
        """Check for unread emails and upcoming events."""
        updates = []
        try:
            # Unread count
            email_data = await self._check_email({"count": 1, "query": "is:unread"})
            unread = email_data.get("total", 0)
            if unread > 0:
                latest = email_data.get("emails", [{}])[0]
                updates.append({
                    "type": "card",
                    "title": f"Unread ({unread})",
                    "body": f"From {latest.get('from', '?').split('<')[0].strip()}: {latest.get('subject', '')}",
                    "integration": self.name,
                })

            # Next event within 30 minutes
            cal_data = await self._check_calendar({"days_ahead": 1})
            for ev in cal_data.get("events", []):
                start_str = ev.get("start", "")
                if "T" in start_str:
                    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    diff = (start - datetime.now(start.tzinfo)).total_seconds()
                    if 0 < diff < 1800:  # Within 30 min
                        mins = int(diff / 60)
                        updates.append({
                            "type": "card",
                            "title": f"In {mins} min",
                            "body": ev.get("title", "Meeting"),
                            "integration": self.name,
                        })
                        break
        except Exception:
            pass
        return updates if updates else None

    def get_context_for_llm(self) -> str | None:
        return "You have access to Gmail and Google Calendar. You can check emails, send emails, check the schedule, and create events."
