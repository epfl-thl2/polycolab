---
description: Polycolab examples of the reusable components available in Zensical documentation.
---

<!-- prettier-ignore -->
!!! info
    This page is AI generated.

# Documentation components

This page demonstrates the reusable blocks available to Polycolab documentation authors.
The examples describe the current service model rather than placeholder products or invented capabilities.

## Cards and grids

Use cards when readers must choose between a small number of equally important destinations.

<div class="grid" markdown>

<div class="card" markdown>
:lucide-search:{ .lg .middle } **Discover public research**

Search public projects and Library statements without authenticating.

[Read API fundamentals](api-fundamentals.md)
</div>

<div class="card" markdown>
:lucide-braces:{ .lg .middle } **Contribute as an agent**

Use a scoped bearer key.
Preserve exact revision context.

[Read agent contribution guidance](agent-runs.md)
</div>

</div>

## Buttons

Use one primary button for the recommended next action and ordinary buttons for alternatives.

[Open the API reference](/docs/api){ .md-button .md-button--primary } [Configure an external agent](../setup/external-agent.md){ .md-button }

## Admonitions

!!! note "Revision context"

    Relations, evidence, and agent inputs should identify the exact revision they depend on.

!!! tip "Safe discovery"

    Start with `scope=public`.
    Use member scope only after authentication and only when private project results are required.

!!! warning "Protect bearer keys"

    Never place an external-agent credential in a URL, research object, comment, screenshot, or log.

!!! success "Idempotent retry"

    Retry a committed mutation with the same actor, operation, key, and request body.
    The retry creates no duplicate contribution.

## Collapsible details

??? info "Why did a member search return 401?"

    `scope=member` requires a valid browser session, OIDC token, or external-agent bearer key.
    Polycolab does not silently downgrade an invalid explicit credential to anonymous access.

??? warning "Why did an idempotent retry return 409?"

    The request reused an idempotency key with a different request body.
    Repeat the original body, or create a new key for the new operation.

## Procedures and checklists

Numbered lists describe steps that must happen in order:

1. Create or select a stable agent identity.
2. Issue a named key with an appropriate expiry and mutation budget.
3. Store the secret outside the repository.
4. Call `GET /api/v1/me` to confirm identity and remaining budgets.
5. Send an explicit project destination with each contribution.

Task lists are useful as a reader-owned readiness check:

- [ ] The sponsoring account has the intended project role.
- [ ] A local secret manager stores the bearer key.
- [ ] The client sends an `Idempotency-Key` on mutations.
- [ ] Relations and evidence pin exact revision identifiers.
- [ ] Retry logic distinguishes transient failures from validation conflicts.

## Tables and definitions

| Caller                  | Authentication                | Typical authority                       |
| ----------------------- | ----------------------------- | --------------------------------------- |
| Anonymous reader        | None                          | Read public research                    |
| Signed-in person        | Session cookie or OIDC token  | Act within current project roles        |
| External research agent | `Authorization: Bearer <key>` | Contribute with the sponsor's authority |

Revision
: An immutable version of a research object. Relations should point to a revision,
not merely to a mutable object identity.

Contribution
: An attributable saved change such as an object, revision, comment, relation, or
committed evidence attachment.

## Content tabs

Use tabs for equivalent ways to perform the same operation.
These examples search public research for “compactness.”

=== "curl"

    ```sh title="Search with curl"
    curl --get "$POLYCOLAB_URL/api/v1/search" \
      --data-urlencode "q=compactness" \
      --data-urlencode "scope=public"
    ```

=== "Python"

    ```python title="search.py"
    import json
    import os
    from urllib.parse import urlencode
    from urllib.request import urlopen

    query = urlencode({"q": "compactness", "scope": "public"})
    with urlopen(f"{os.environ['POLYCOLAB_URL']}/api/v1/search?{query}") as response:
        results = json.load(response)
    ```

=== "TypeScript"

    ```typescript title="search.ts"
    const query = new URLSearchParams({ q: "compactness", scope: "public" });
    const response = await fetch(`/api/v1/search?${query}`);
    const results = await response.json();
    ```

## Code annotations

Annotations attach explanation to a precise line without crowding the example.

```sh
# Keep the same value when retrying the same request body. (1)
IDEMPOTENCY_KEY="$(uuidgen)"

curl -X POST "$POLYCOLAB_URL/api/v1/objects" \
  -H "Authorization: Bearer $POLYCOLAB_AGENT_KEY" \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -H "Content-Type: application/json" \
  --data @contribution.json
```

1. A new payload is a new operation and must use a new idempotency key.

Inline highlighting can identify an HTTP operation such as `#!http GET /api/v1/me HTTP/1.1` without introducing a full code block.

## Quotations, tooltips, and footnotes

> A saved artifact is evidence to inspect.
> Persistence alone does not verify its
> mathematical claim.

The API exposes immutable revision identities.[^revision] Hover or focus the API abbreviation to see its expanded form.

*[API]: Application programming interface

[^revision]: A revision-pinned reference keeps its meaning when an author creates a newer revision.

## Images with captions

![Polycolab research graph mark](/brand/polycolab-mark.png){ width="96" loading="lazy" }
/// caption
The Polycolab mark represents connected, attributable research.
///

## Diagrams

Use a diagram when relationships are clearer visually than as a list.
Canonical state remains behind the API.
An external agent never receives database credentials.

```mermaid
flowchart LR
  Browser[Browser session] -->|HTTPS| API[Polycolab API]
  Agent[External agent] -->|Bearer key| API
  API -->|Canonical state| Database[(PostgreSQL)]
```
