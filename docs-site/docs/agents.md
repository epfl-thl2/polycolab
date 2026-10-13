# Agent library

Open [Agents](/agents) to find reusable prompts, skills and plugins for your agents.
Public browsing does not require an account.

## Find and use an entry

1. Search the Library by title, description or tag, or filter by Prompt, Skill or Plugin.
2. Open an entry and read its content, usage instructions, author, license and versions.
3. Copy prompt text or copy/download a SKILL.md file for use in your agent.
   For plugins, open the source and follow its setup instructions in the listed runtime.
4. Use **Copy version link** to share the exact version you inspected.

Agents does not automatically install plugins, enable tools or send prompts to a chat.
Runtime requirements and upstream setup instructions still apply.

## Contribute

1. Sign in and select **Contribute**.
2. Choose a type, enter a title and description, and add content and usage instructions.
   Skills require one SKILL.md file with YAML frontmatter containing `name` and `description`.
   You can import a UTF-8 Markdown file; supporting files can be linked through the source URL.
   Plugins require their target runtime, source URL and setup instructions.
3. Select **Save draft** to keep the entry private in **Yours**.
4. Add the license, select **Preview publication**, and inspect all the content.
5. Select **Publish** to make an immutable version available immediately.

Publication does not mean the content has been tested or endorsed.
Only publish content you have permission to share.

## Copy, update and archive

Select **Make a copy** on a public entry to create your own private draft.
The copy preserves the original version link and license.
Keep the original attribution when publishing your adaptation.

Open **Yours** to edit your entries.
Saving edits changes only the private draft; publishing creates a new public version.
Earlier version links keep their earlier content.
If an entry changes while you are editing, your save fails without overwriting it.
Use **Reload saved draft** only after preserving any inputs you need.

Save your draft before archiving an entry.
Archived entries disappear from discovery and cannot be copied, but their published versions remain readable.
Use **Restore entry** to continue editing.
A moderator-hidden entry remains unavailable publicly until a moderator restores it, even if you publish an update.
Copies already created are independent entries.

## Connections

[Connections](/agents/connections) manages existing external-agent identities.
API keys and model providers remain in Settings.
See the [external-agent setup guide](setup/external-agent.md).
