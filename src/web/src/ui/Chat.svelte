<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  import { MessageSquare, Plus, Paperclip, ArrowUp } from '@lucide/svelte';
  import PreviewNotice from './PreviewNotice.svelte';
  import PlannedBadge from './PlannedBadge.svelte';
</script>

<main id="main" class="page discovery-page chat-page" tabindex="-1">
  <header class="discovery-heading">
    <div class="discovery-title">
      <h1>Chat</h1>
      <PlannedBadge />
    </div>
    <p>
      Explore an idea with a server-hosted research agent, then turn useful results into project
      research.
    </p>
  </header>
  <PreviewNotice
    message="Server-hosted chat is coming soon. This layout preview cannot send messages, connect models or run tools."
  />
  <section class="chat-preview" aria-label="Planned chat layout">
    <details class="chat-sidebar" aria-label="Conversation history preview">
      <summary>Conversation history</summary>
      <Button variant="outline" disabled><Plus size={16} aria-hidden="true" />New chat</Button>
      <h2>Conversations</h2>
      <p>Your private conversations will appear here.</p>
      <p class="muted">Resume an investigation without choosing a project first.</p>
    </details>
    <div class="chat-conversation">
      <div class="chat-welcome">
        <MessageSquare size={28} aria-hidden="true" />
        <h2>Start an investigation</h2>
        <p>Explore an idea, examine an argument, or work through a mathematical question.</p>
      </div>
      <div class="chat-prompts" aria-label="Example conversation starters">
        <p>Explore possible approaches to a problem</p>
        <p>Find gaps in a mathematical argument</p>
        <p>Understand the assumptions behind a result</p>
      </div>
      <div class="chat-composer">
        <label for="planned-message">Message <span class="muted">· preview only</span></label
        ><textarea
          id="planned-message"
          disabled
          rows="3"
          placeholder="What would you like to investigate?"></textarea>
        <div class="chat-composer-actions">
          <Button variant="ghost" disabled
            ><Paperclip size={16} aria-hidden="true" />Attach context</Button
          ><Button disabled aria-label="Send message"
            ><ArrowUp size={16} aria-hidden="true" /></Button
          >
        </div>
      </div>
    </div>
    <details class="chat-configuration" aria-label="Session configuration preview">
      <summary>Session setup</summary>

      <p class="muted">Choose compatible components when chat becomes available.</p>
      <dl>
        <div>
          <dt>Harness</dt>
          <dd>The runtime that operates the agent and its tools.</dd>
        </div>
        <div>
          <dt>Provider & model</dt>
          <dd>The language model powering the conversation.</dd>
        </div>
        <div>
          <dt>Agent role</dt>
          <dd>Researcher, Critic or other supported instructions.</dd>
        </div>
        <div>
          <dt>Context</dt>
          <dd>Only research and files you explicitly attach.</dd>
        </div>
        <div>
          <dt>Destination</dt>
          <dd>Conversation only, until you choose a project.</dd>
        </div>
      </dl>
    </details>
  </section>
  <section class="chat-next" aria-label="From conversation to research">
    <div>
      <h2>Keep the conversation private</h2>
      <p>
        General Chat will start without project write access. You will choose which results to save
        or continue in a project.
      </p>
      <p>
        In a public project, saved research is public; the private conversation is not automatically
        shared.
      </p>
    </div>
    <div>
      <h2>Work with an agent today</h2>
      <p>Connect an external agent running on your own machine or infrastructure.</p>
      <div class="chat-links">
        <Button href="/agents/connections">Connect an external agent</Button><Button
          href="/projects?scope=public"
          variant="outline">Browse projects</Button
        >
      </div>
    </div>
  </section>
</main>

<style>
  summary {
    cursor: pointer;
    font-weight: 600;
  }
  .chat-conversation {
    width: 100%;
    max-width: 820px;
    margin-inline: auto;
  }
  .chat-links {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    flex-wrap: wrap;
  }
  h2,
  p {
    margin: 0;
  }
  h2 {
    font-size: 1rem;
  }
  .chat-preview p,
  .chat-next p {
    margin-top: 0.65rem;
  }
  .chat-preview {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    border: 1px solid var(--line);
    border-radius: 0.75rem;
    overflow: hidden;
  }
  .chat-sidebar,
  .chat-configuration {
    padding: 1.25rem;
    background: var(--surface);
    font-size: 0.85rem;
  }
  .chat-sidebar {
    border-bottom: 1px solid var(--line);
  }
  .chat-sidebar h2 {
    margin-top: 2rem;
  }
  .chat-configuration {
    border-top: 1px solid var(--line);
  }
  dl {
    display: grid;
    gap: 1.1rem;
  }
  dt {
    font-weight: 600;
  }
  dd {
    margin: 0.3rem 0 0;
    color: var(--muted-foreground);
  }
  .chat-conversation {
    display: grid;
    align-content: center;
    gap: 1.5rem;
    padding: 2rem;
    min-width: 0;
  }
  .chat-welcome {
    display: grid;
    justify-items: center;
    text-align: center;
    gap: 0.65rem;
    padding: 1rem 0;
  }
  .chat-welcome h2 {
    font-size: 1.5rem;
  }
  .chat-welcome p {
    max-width: 40ch;
    color: var(--muted-foreground);
  }
  .chat-prompts {
    display: grid;
    gap: 0.5rem;
    font-size: 0.85rem;
  }
  .chat-prompts p {
    border: 1px solid var(--line);
    border-radius: 0.5rem;
    padding: 0.75rem;
    margin: 0;
  }
  .chat-composer {
    border: 1px solid var(--line);
    border-radius: 0.75rem;
    padding: 0.75rem;
    font-size: 0.85rem;
  }
  textarea {
    display: block;
    width: 100%;
    resize: none;
    padding: 0.75rem 0;
    background: transparent;
    border: none;
  }
  .chat-composer-actions {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .chat-next {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
  }
  .chat-links {
    margin-top: 1rem;
  }
  @media (max-width: 1000px) {
    .chat-preview {
      grid-template-columns: minmax(0, 1fr);
    }
    .chat-configuration {
      grid-column: 1 / -1;
      border-left: 0;
      border-top: 1px solid var(--line);
    }
    dl {
      grid-template-columns: repeat(2, 1fr);
    }
  }
  @media (max-width: 600px) {
    .chat-preview,
    .chat-next {
      grid-template-columns: 1fr;
    }
    .chat-sidebar {
      border-right: 0;
      border-bottom: 1px solid var(--line);
    }
    .chat-sidebar h2 {
      margin-top: 1rem;
    }
    .chat-conversation {
      padding: 1rem;
    }
    dl {
      grid-template-columns: 1fr;
    }
  }
</style>
