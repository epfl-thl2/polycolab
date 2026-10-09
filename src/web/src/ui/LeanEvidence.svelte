<script lang="ts">
  import type { LeanFormalizationView } from '../lib/execution-evidence';
  let { formalizations }: { formalizations: LeanFormalizationView[] } = $props();
</script>

<section aria-labelledby="lean-evidence-heading">
  <h2 id="lean-evidence-heading">Lean formalizations</h2>
  <p class="muted">
    Compilation, API-evaluated proof policy, axioms and unfinished work are machine observations.
    Human-authored formal/informal correspondence remains an independent history.
  </p>
  {#each formalizations as formalization (formalization.formalizationRevision.revisionId)}<article
      class="panel"
      aria-labelledby={`formalization-${formalization.formalizationRevision.revisionId}`}
    >
      <header>
        <div>
          <h3 id={`formalization-${formalization.formalizationRevision.revisionId}`}>
            <a href={formalization.formalizationRevision.href}
              >{formalization.formalizationRevision.title}</a
            >
          </h3>
        </div>
        <strong class="state-label">{formalization.state.replace('_', ' ')}</strong>
      </header>
      <p>
        Result {formalization.resultId} · job {formalization.jobId} · environment
        {formalization.environment}
      </p>
      <p>
        Exact target <a href={formalization.targetRevision.href}
          >{formalization.targetRevision.title}</a
        >
        · version {formalization.targetRevision.revisionId}
      </p>
      <p>
        {formalization.attribution.actorKind === 'AGENT' ? 'Agent' : 'Human'}
        {formalization.attribution.displayName}
      </p>
      {#if formalization.historical}<p class="state-label">
          Historical result for an earlier exact target, source, environment or policy selection.
        </p>{/if}
      <p class="muted">
        Compatible cache {formalization.cache.reused ? 'reused' : 'not reused'} · authorization scope
        {formalization.cache.authorizationScope}. Internal cache keys are not exposed.
      </p>
      {#each formalization.declarations as declaration (declaration.name)}<section
          aria-labelledby={`declaration-${formalization.formalizationRevision.revisionId}-${declaration.name}`}
        >
          <h4
            id={`declaration-${formalization.formalizationRevision.revisionId}-${declaration.name}`}
          >
            {declaration.name}
          </h4>
          <p>
            Declaration {declaration.declarationId} · module {declaration.modulePath}
          </p>
          <dl>
            <div>
              <dt>Compilation</dt>
              <dd>{declaration.compilation}</dd>
            </div>
            <div>
              <dt>API-evaluated proof policy</dt>
              <dd>{declaration.proofPolicyOutcome} · policy {declaration.policyVersion}</dd>
            </div>
            <div>
              <dt>Unfinished</dt>
              <dd>{declaration.unfinished ? 'Yes' : 'No'}</dd>
            </div>
          </dl>
          <h5>Transitive axioms</h5>
          <ul>
            {#each declaration.axioms as axiom (axiom.name)}<li>
                {axiom.name} · {axiom.policy}
              </li>{:else}<li>None reported.</li>{/each}
          </ul>
          {#if declaration.diagnostics.length}<h5>Diagnostics</h5>
            <ul>
              {#each declaration.diagnostics as diagnostic, index (`${declaration.name}:${index}`)}<li
                >
                  {diagnostic}
                </li>{/each}
            </ul>{/if}
          <h5>Human formal/informal correspondence</h5>
          <ol>
            {#each declaration.correspondenceHistory as assessment (`${assessment.formalizationRevisionId}:${assessment.informalTargetRevisionId}:${assessment.createdAt}`)}<li
              >
                <strong>{assessment.status}</strong> by {assessment.author} · exact pair
                {assessment.formalizationRevisionId} ↔ {assessment.informalTargetRevisionId} ·
                {assessment.createdAt}
              </li>{:else}<li>No human correspondence assessment for this exact pair.</li>{/each}
          </ol>
        </section>{/each}
    </article>{:else}<p>No Lean formalizations are visible.</p>{/each}
</section>

<style>
  section,
  article,
  dl {
    display: grid;
    gap: 0.75rem;
  }
  header,
  dl > div {
    display: flex;
    justify-content: space-between;
    align-items: start;
    gap: 1rem;
  }
  h2,
  h3,
  h4,
  h5,
  p,
  ul,
  dl,
  dd {
    margin-top: 0;
  }
  dd {
    margin-left: 0;
  }
  .state-label {
    display: inline-block;
    width: fit-content;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
  }
</style>
