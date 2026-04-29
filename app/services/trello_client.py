"""Trello REST API client for the validation gate between blog generation and translation."""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.trello.com/1"


class TrelloClient:
    """Wraps the Trello REST API for the blog validation gate."""

    def __init__(self):
        self.api_key = os.environ.get("TRELLO_API_KEY", "")
        self.api_token = os.environ.get("TRELLO_API_TOKEN", "")
        self.board_id = os.environ.get("TRELLO_BOARD_ID", "")
        self.pending_list_name = os.environ.get("TRELLO_PENDING_LIST_NAME", "To Do")
        self.translating_list_name = os.environ.get("TRELLO_TRANSLATING_LIST_NAME", "Doing")
        self.done_list_name = os.environ.get("TRELLO_DONE_LIST_NAME", "Done")
        self.checklist_name = os.environ.get("TRELLO_CHECKLIST_NAME", "Validations")
        self.checklist_item_1 = os.environ.get("TRELLO_CHECKLIST_ITEM_1", "Validated by Haleema")
        self.checklist_item_2 = os.environ.get("TRELLO_CHECKLIST_ITEM_2", "Validated by Jeremy")
        self._list_ids = {}
        self._session = requests.Session()

    def _request(self, method, path, **kwargs):
        url = f"{BASE_URL}{path}"
        params = kwargs.pop("params", {})
        params["key"] = self.api_key
        params["token"] = self.api_token

        logger.info("%s %s", method.upper(), url)

        last_exc = None
        for attempt in range(3):
            resp = self._session.request(method, url, params=params, **kwargs)
            if resp.status_code == 429:
                sleep_secs = 2 ** attempt  # 1s, 2s, 4s
                logger.info("Rate limited (429); sleeping %ds before retry", sleep_secs)
                time.sleep(sleep_secs)
                last_exc = RuntimeError(f"Trello rate limit (429) on {method.upper()} {path}")
                continue
            return resp

        raise last_exc

    def _raise_for_status(self, resp, path):
        if not resp.ok:
            raise RuntimeError(
                f"Trello API error {resp.status_code} on {path}: {resp.text[:300]}"
            )

    def resolve_list_ids(self):
        resp = self._request("get", f"/boards/{self.board_id}/lists")
        self._raise_for_status(resp, f"/boards/{self.board_id}/lists")

        self._list_ids = {lst["name"]: lst["id"] for lst in resp.json()}

        required = [self.pending_list_name, self.translating_list_name, self.done_list_name]
        missing = [name for name in required if name not in self._list_ids]
        if missing:
            raise RuntimeError(
                f"The following Trello list names were not found on the board: {missing}"
            )

        logger.info("Resolved list IDs: %s", self._list_ids)
        return self._list_ids

    def create_validation_card(self, blog_title, drive_url):
        # KeyError intentionally propagates if resolve_list_ids() was not called
        id_list = self._list_ids[self.pending_list_name]

        resp = self._request(
            "post",
            "/cards",
            data={
                "name": blog_title,
                "desc": f"Review this blog before translation:\n\n{drive_url}",
                "idList": id_list,
            },
        )
        self._raise_for_status(resp, "/cards")
        card = resp.json()
        card_id = card["id"]

        resp = self._request(
            "post",
            "/checklists",
            data={"idCard": card_id, "name": self.checklist_name},
        )
        self._raise_for_status(resp, "/checklists")
        checklist_id = resp.json()["id"]

        for item_name in (self.checklist_item_1, self.checklist_item_2):
            resp = self._request(
                "post",
                f"/checklists/{checklist_id}/checkItems",
                data={"name": item_name, "checked": "false"},
            )
            self._raise_for_status(resp, f"/checklists/{checklist_id}/checkItems")

        logger.info("Created Trello card %r for %r", card_id, blog_title)
        return card_id

    def get_card_checklist_state(self, card_id):
        resp = self._request("get", f"/cards/{card_id}/checklists")

        if resp.status_code == 404:
            return None

        self._raise_for_status(resp, f"/cards/{card_id}/checklists")

        for checklist in resp.json():
            if checklist["name"] == self.checklist_name:
                state = {
                    item["name"]: item["state"] == "complete"
                    for item in checklist.get("checkItems", [])
                }
                logger.info("Checklist state for card %r: %s", card_id, state)
                return state

        state = {}
        logger.info("Checklist state for card %r: %s", card_id, state)
        return state

    def move_card_to_list(self, card_id, list_name):
        resp = self._request(
            "put",
            f"/cards/{card_id}",
            data={"idList": self._list_ids[list_name]},
        )
        self._raise_for_status(resp, f"/cards/{card_id}")
        logger.info("Moved card %r to list %r", card_id, list_name)

    def add_comment(self, card_id, text):
        resp = self._request(
            "post",
            f"/cards/{card_id}/actions/comments",
            data={"text": text},
        )
        self._raise_for_status(resp, f"/cards/{card_id}/actions/comments")
        logger.info("Added comment to card %r", card_id)
