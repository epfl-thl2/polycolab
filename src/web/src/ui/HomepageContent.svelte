<section class="getting-started" aria-labelledby="home-start-title">
  <h2 id="home-start-title">Turn a question into collaborative research</h2>
  <ol>
    <li>
      <h3>Start with a question</h3>
      <p>Bring a problem of your own or build on work already shared by the community.</p>
    </li>
    <li>
      <h3>Develop it together</h3>
      <p>
        Organize statements, proof sketches and evidence in a public or private project. Invite
        collaborators to contribute.
      </p>
    </li>
    <li>
      <h3>Work with an agent</h3>
      <p>Connect an AI agent to help explore questions and develop proofs.</p>
    </li>
  </ol>
</section>

<style>
  section {
    display: grid;
    gap: 16px;
  }
  h2,
  h3,
  p {
    margin: 0;
  }
  h2 {
    font-size: 22px;
    line-height: 1.3;
    letter-spacing: -0.02em;
  }
  h3 {
    font-size: 16px;
    line-height: 1.4;
    font-weight: 600;
  }
  p {
    color: var(--muted-foreground);
    line-height: 1.6;
  }
  ol {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 24px;
    list-style: none;
    counter-reset: steps;
    padding: 0;
    margin: 0;
  }
  li {
    display: grid;
    align-content: start;
    gap: 8px;
    counter-increment: steps;
  }
  li h3::before {
    content: counter(steps) '. ';
    color: var(--brand);
  }
  @media (max-width: 700px) {
    ol {
      grid-template-columns: 1fr;
    }
  }
</style>
