<script lang="ts">
  import { untrack } from 'svelte';
  import type { Project, ObjectVersion } from '../../../lib/research-api';
  import type { ProjectTab } from '../../../lib/project-tabs';
  import type { Activity } from '../../../lib/history-api';
  import type { ProjectMap } from '../../../lib/project-map';
  import ProjectPage from '../ProjectPage.svelte';
  let {
    project,
    tabs = $bindable(),
    activeId,
    selectedResearch = $bindable(),
    selectedActivity = $bindable(),
    mapData = $bindable(),
    mapObjectId = $bindable(''),
    mapPanelTab = $bindable('body'),
    onCreated,
    onInspect,
  }: {
    project: Project;
    tabs: ProjectTab[];
    activeId: string;
    selectedResearch?: { version: ObjectVersion; searchResult: boolean };
    selectedActivity?: Activity;
    mapData?: ProjectMap;
    mapObjectId?: string;
    mapPanelTab?: string;
    onCreated: (id: string) => void;
    onInspect: () => void;
  } = $props();
</script>

{#each tabs.filter((t) => t.kind !== 'file') as tab (tab.id)}<div
    class="page-panel"
    class:chat-panel={tab.kind === 'chat'}
    hidden={tab.id !== activeId}
  >
    <ProjectPage
      {project}
      href={tab.href}
      active={tab.id === activeId}
      onState={(update) =>
        untrack(() => {
          if (tab.kind === 'chat') return;
          const current = tabs.find((item) => item.id === tab.id);
          if (!current) return;
          const label = update.label ?? current.label;
          // Session effects report state repeatedly; unchanged reports must not rerender the page.
          if (label === current.label && update.dirty === Boolean(current.dirty)) return;
          tabs = tabs.map((item) =>
            item.id === current.id ? { ...item, label, dirty: update.dirty } : item,
          );
        })}
      onCreated={(id) => {
        tabs = tabs.filter((t) => t.id !== tab.id);
        onCreated(id);
      }}
      bind:selectedResearch
      bind:selectedActivity
      bind:mapData
      bind:mapObjectId
      bind:mapPanelTab
      {onInspect}
    />
  </div>{/each}

<style>
  .page-panel {
    min-height: 0;
    overflow: auto;
    flex: 1;
    padding: 24px;
  }
  .page-panel[hidden] {
    display: none;
  }
  .chat-panel {
    width: 100%;
    max-width: 880px;
    margin: 0 auto;
  }
  @media (max-width: 760px) {
    .page-panel {
      padding: 16px;
    }
  }
</style>
