from .http import APIError

FIELDS = "id text status dueAt sentAt externalLink schedulingType channelId metadata { ... on TiktokMetadata { title } } assets { ... on ImageAsset { source } }"


class Buffer:
    def __init__(self, http, token, organization, channel):
        self.http, self.token, self.organization, self.channel = http, token, organization, channel

    def query(self, document, variables=None, mutation=False):
        result = self.http.json("https://api.buffer.com", {"query": document, "variables": variables or {}},
                                self.token, safe_retry=not mutation)
        if result.get("errors") or not isinstance(result.get("data"), dict):
            # A GraphQL mutation error does not necessarily prove no write happened.
            raise APIError("Buffer GraphQL", uncertain=mutation)
        return result["data"]

    def discover(self):
        account = self.query("query { account { organizations { id name } } }")["account"]
        found = []
        for org in account["organizations"]:
            channels = self.query("query($input: ChannelsInput!) { channels(input: $input) { id name service isDisconnected isLocked isQueuePaused } }",
                                  {"input": {"organizationId": org["id"]}})["channels"]
            found.append({"organization": org, "channels": channels})
        return found

    def preflight(self):
        channels = self.query("query($input: ChannelsInput!) { channels(input: $input) { id service isDisconnected isLocked isQueuePaused } }",
                              {"input": {"organizationId": self.organization}})["channels"]
        channel = next((x for x in channels if x["id"] == self.channel), None)
        if not channel or channel["service"] != "tiktok":
            raise RuntimeError("Configured channel is not a TikTok channel in this organization")
        if any(channel.get(k) for k in ("isDisconnected", "isLocked", "isQueuePaused")):
            raise RuntimeError("TikTok channel is disconnected, locked, or paused")

    def get(self, post_id):
        data = self.query(f"query($input: PostInput!) {{ post(input: $input) {{ {FIELDS} }} }}", {"input": {"id": post_id}})
        if not data.get("post"):
            raise RuntimeError("Previously accepted Buffer post could not be found; refusing to recreate")
        return data["post"]

    def reconcile(self, entry):
        """Read ALL pages; an absent result never authorizes retrying an uncertain write."""
        query = f"query($input: PostsInput!, $after: String) {{ posts(input: $input, first: 100, after: $after) {{ edges {{ node {{ {FIELDS} }} }} pageInfo {{ hasNextPage endCursor }} }} }}"
        after, matches = None, []
        for _ in range(30):
            result = self.query(query, {"input": {"organizationId": self.organization,
                "filter": {"channelIds": [self.channel], "createdAt": {"start": entry["attempted_at"]}}}, "after": after})["posts"]
            for edge in result["edges"]:
                post = edge["node"]
                # Exact caption includes mandatory disclosure; URL is secondary evidence.
                if (post["text"] == entry["caption"] and post["channelId"] == self.channel
                        and (post.get("metadata") or {}).get("title") == entry["title"]):
                    matches.append(post)
            page = result["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        else:
            raise RuntimeError("Reconciliation page limit reached; no mutation permitted")
        if len(matches) > 1:
            raise RuntimeError("Multiple matching posts; manual investigation required")
        return matches[0] if matches else None

    def create(self, entry, now=False):
        input_value = {
            "channelId": self.channel, "text": entry["caption"], "schedulingType": "automatic",
            "mode": "shareNow" if now else "customScheduled", "aiAssisted": True,
            "assets": [{"image": {"url": url}} for url in entry.get("image_urls", [entry["image_url"]])],
            # isAiGenerated is intentionally omitted: Buffer rejects it on TikTok photos.
            "metadata": {"tiktok": {"title": entry["title"]}},
        }
        if not now:
            input_value["dueAt"] = entry["due_at"]
        result = self.query(f"mutation($input: CreatePostInput!) {{ createPost(input: $input) {{ __typename ... on PostActionSuccess {{ post {{ {FIELDS} }} }} ... on MutationError {{ message }} }} }}",
                            {"input": input_value}, mutation=True)["createPost"]
        if not result.get("post"):
            raise APIError("Buffer typed mutation rejection", 400, uncertain=False)
        return result["post"]
