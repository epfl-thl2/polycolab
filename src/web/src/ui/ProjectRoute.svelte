<script lang="ts">
  import Project from './Project.svelte';
  let { projectId, path }: { projectId: string; path: string } = $props();
</script>

<Project {projectId} {path} />
