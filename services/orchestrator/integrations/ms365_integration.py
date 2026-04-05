"""
Samantha OS — Microsoft 365 Integration
Outlook Mail, Calendar, OneDrive, and Contacts via Microsoft Graph API.

Setup:
  1. Register app at https://portal.azure.com → App registrations
  2. Add permissions: Mail.Read, Mail.Send, Calendars.ReadWrite, Contacts.Read
  3. Create a client secret
  4. Set MS365_CLIENT_ID, MS365_CLIENT_SECRET, MS365_TENANT_ID in .env
  5. Run OAuth flow: python -m integrations.ms365_oauth

Uses device code flow for headless/server auth.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from integrations import BaseIntegration, IntegrationAction, IntegrationStatus

logger = logging.getLogger("samantha.ms365")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_BASE = "https://login.microsoftonline.com"
SCOPES = "Mail.Read Mail.Send Calendars.ReadWrite Contacts.Read User.Read offline_access"


class MS365Integration(BaseIntegration):
    name = "ms365"
    display_name = "Microsoft 365 (Outlook + Calendar)"
    description = "Read/send Outlook email, manage calendar, access contacts"
    icon = "📬"
    requires_auth = True

    def __init__(self):
        super().__init__()
        self.client_id: str = ""
        self.client_secret: str = ""
        self.tenant_id: str = ""
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expiry: datetime | None = None
        self._token_file: str = "config/ms365_token.json"

    async def initialize(self, config: dict) -> bool:
        self.client_id = config.get("client_id", os.getenv("MS365_CLIENT_ID", ""))
        self.client_secret = config.get("client_secret", os.getenv("MS365_CLIENT_SECRET", ""))
        self.tenant_id = config.get("tenant_id", os.getenv("MS365_TENANT_ID", "common"))
        self._token_file = config.get("token_file", "config/ms365_token.json")

        if not self.client_id:
            logger.warning("MS365: No client_id configured")
            return False

        # Load cached token
        if os.path.exists(self._token_file):
            with open(self._token_file) as f:
                data = json.load(f)
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                exp = data.get("expiry")
                if exp:
                    self.token_expiry = datetime.fromisoformat(exp)

            if self.token_expiry and datetime.now() > self.token_expiry:
                await self._refresh_access_token()

            if self.access_token:
                logger.info("MS365: using cached token")
                return True

        logger.info("MS365: OAuth required. Run: python -m integrations.ms365_oauth")
        return False

    async def _refresh_access_token(self):
        if not self.refresh_token:
            return
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{AUTH_BASE}/{self.tenant_id}/oauth2/v2.0/token", data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                    "scope": SCOPES,
                })
                data = resp.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token", self.refresh_token)
                self.token_expiry = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
                self._save_token()
                logger.info("MS365: token refreshed")
        except Exception as e:
            logger.error(f"MS365 refresh failed: {e}")

    def _save_token(self):
        with open(self._token_file, "w") as f:
            json.dump({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expiry": self.token_expiry.isoformat() if self.token_expiry else None,
            }, f)

    async def _graph(self, method: str, path: str, **kwargs) -> dict:
        if self.token_expiry and datetime.now() > self.token_expiry:
            await self._refresh_access_token()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{GRAPH_BASE}{path}", headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="check_outlook",
                description="Check recent Outlook emails",
                keywords=["outlook", "email", "mail", "inbox", "unread"],
                parameters=["count", "filter"],
                examples=["Check my Outlook", "Any new emails in Outlook?"],
            ),
            IntegrationAction(
                name="send_outlook",
                description="Send an email via Outlook",
                keywords=["send outlook", "outlook email", "mail via outlook"],
                parameters=["to", "subject", "body"],
                examples=["Send an email to anna@company.com via Outlook"],
            ),
            IntegrationAction(
                name="check_outlook_calendar",
                description="Check Outlook calendar events",
                keywords=["outlook calendar", "meetings", "schedule", "outlook schedule"],
                parameters=["days_ahead"],
                examples=["What's on my Outlook calendar?", "Teams meetings today?"],
            ),
            IntegrationAction(
                name="create_outlook_event",
                description="Create an Outlook calendar event",
                keywords=["schedule outlook", "teams meeting", "book meeting", "outlook event"],
                parameters=["title", "start", "end", "attendees", "is_teams"],
                examples=["Schedule a Teams meeting with the team"],
            ),
            IntegrationAction(
                name="search_outlook_contacts",
                description="Search Outlook / Azure AD contacts",
                keywords=["outlook contact", "company directory", "find colleague"],
                parameters=["query"],
                examples=["Find Erik in the company directory"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        handlers = {
            "check_outlook": self._check_mail,
            "send_outlook": self._send_mail,
            "check_outlook_calendar": self._check_calendar,
            "create_outlook_event": self._create_event,
            "search_outlook_contacts": self._search_contacts,
        }
        handler = handlers.get(action_name)
        if not handler:
            return {"error": f"Unknown action: {action_name}"}
        return await handler(params)

    async def _check_mail(self, params: dict) -> dict:
        count = params.get("count", 5)
        try:
            data = await self._graph("GET", "/me/mailFolders/inbox/messages", params={
                "$top": count, "$orderby": "receivedDateTime desc",
                "$select": "subject,from,receivedDateTime,bodyPreview,isRead",
            })
            emails = []
            for msg in data.get("value", []):
                emails.append({
                    "subject": msg.get("subject", "(no subject)"),
                    "from": msg.get("from", {}).get("emailAddress", {}).get("name", "Unknown"),
                    "from_email": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "date": msg.get("receivedDateTime", ""),
                    "preview": msg.get("bodyPreview", "")[:150],
                    "read": msg.get("isRead", True),
                })
            return {"emails": emails}
        except Exception as e:
            return {"error": str(e)}

    async def _send_mail(self, params: dict) -> dict:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to:
            return {"error": "No recipient specified"}
        try:
            await self._graph("POST", "/me/sendMail", json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                }
            })
            return {"sent": True, "to": to, "subject": subject}
        except Exception as e:
            return {"error": str(e)}

    async def _check_calendar(self, params: dict) -> dict:
        days = params.get("days_ahead", 1)
        now = datetime.utcnow()
        end = now + timedelta(days=days)
        try:
            data = await self._graph("GET", "/me/calendarView", params={
                "startDateTime": now.isoformat() + "Z",
                "endDateTime": end.isoformat() + "Z",
                "$orderby": "start/dateTime",
                "$top": 20,
                "$select": "subject,start,end,location,isOnlineMeeting,onlineMeetingUrl,attendees",
            })
            events = []
            for ev in data.get("value", []):
                events.append({
                    "title": ev.get("subject", "(no title)"),
                    "start": ev.get("start", {}).get("dateTime", ""),
                    "end": ev.get("end", {}).get("dateTime", ""),
                    "location": ev.get("location", {}).get("displayName", ""),
                    "is_teams": ev.get("isOnlineMeeting", False),
                    "teams_url": ev.get("onlineMeetingUrl", ""),
                    "attendees": [a.get("emailAddress", {}).get("name", "") for a in ev.get("attendees", [])],
                })
            return {"events": events, "period": f"next {days} day(s)"}
        except Exception as e:
            return {"error": str(e)}

    async def _create_event(self, params: dict) -> dict:
        title = params.get("title", "New Meeting")
        start = params.get("start", "")
        end = params.get("end", "")
        attendees = params.get("attendees", [])
        is_teams = params.get("is_teams", False)

        if not start:
            return {"error": "No start time specified"}

        event_body: dict[str, Any] = {
            "subject": title,
            "start": {"dateTime": start, "timeZone": "Europe/Stockholm"},
            "end": {"dateTime": end or start, "timeZone": "Europe/Stockholm"},
            "isOnlineMeeting": is_teams,
        }
        if is_teams:
            event_body["onlineMeetingProvider"] = "teamsForBusiness"
        if attendees:
            event_body["attendees"] = [
                {"emailAddress": {"address": e}, "type": "required"} for e in attendees
            ]

        try:
            result = await self._graph("POST", "/me/events", json=event_body)
            return {
                "created": True, "title": title,
                "teams_url": result.get("onlineMeeting", {}).get("joinUrl", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    async def _search_contacts(self, params: dict) -> dict:
        query = params.get("query", "")
        try:
            data = await self._graph("GET", "/me/contacts", params={
                "$filter": f"contains(displayName,'{query}') or contains(emailAddresses/any(e:e/address),'{query}')",
                "$top": 5,
                "$select": "displayName,emailAddresses,mobilePhone,businessPhones,companyName,jobTitle",
            })
            contacts = []
            for c in data.get("value", []):
                contacts.append({
                    "name": c.get("displayName", "Unknown"),
                    "emails": [e.get("address") for e in c.get("emailAddresses", [])],
                    "phone": c.get("mobilePhone") or (c.get("businessPhones", [None])[0] if c.get("businessPhones") else None),
                    "company": c.get("companyName", ""),
                    "title": c.get("jobTitle", ""),
                })
            return {"contacts": contacts}
        except Exception as e:
            return {"error": str(e)}

    async def get_proactive_updates(self) -> list[dict] | None:
        updates = []
        try:
            mail = await self._check_mail({"count": 1})
            emails = mail.get("emails", [])
            unread = [e for e in emails if not e.get("read")]
            if unread:
                e = unread[0]
                updates.append({
                    "type": "card",
                    "title": "New Outlook email",
                    "body": f"{e['from']}: {e['subject']}",
                    "integration": self.name,
                })

            cal = await self._check_calendar({"days_ahead": 1})
            for ev in cal.get("events", []):
                start_str = ev.get("start", "")
                if start_str:
                    try:
                        start = datetime.fromisoformat(start_str)
                        diff = (start - datetime.utcnow()).total_seconds()
                        if 0 < diff < 1800:
                            mins = int(diff / 60)
                            label = f"Teams meeting in {mins}min" if ev.get("is_teams") else f"In {mins}min"
                            updates.append({
                                "type": "card",
                                "title": label,
                                "body": ev.get("title", "Meeting"),
                                "integration": self.name,
                            })
                            break
                    except ValueError:
                        pass
        except Exception:
            pass
        return updates if updates else None

    def get_context_for_llm(self) -> str | None:
        return "You have access to Outlook email and calendar. You can check emails, send emails, view the schedule, and create meetings (including Teams meetings)."
