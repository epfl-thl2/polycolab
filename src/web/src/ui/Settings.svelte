<script lang="ts">
  import ConfirmAction from './ConfirmAction.svelte';
  import { Confirmation } from '../svelte-lib/confirmation.svelte';
  const confirmation = new Confirmation();
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery } from '@tanstack/svelte-query';
  import { untrack } from 'svelte';
  import { goto } from '$app/navigation';
  import { projectContext, explain } from '../svelte-lib/context';
  import { ApiError, type Project, type Role } from '../lib/research-api';
  let { project }: { project: Project } = $props();
  const { api, query } = projectContext();
  let visibility = $state(untrack(() => project.visibility));
  let name = $state(untrack(() => project.name));
  let description = $state(untrack(() => project.description ?? ''));
  let username = $state('');
  let role = $state<Role>('CONTRIBUTOR');
  let error = $state('');
  let notice = $state('');
  let busy = $state(false);
  const owner = $derived(project.current_user_role === 'OWNER');
  const roles: Role[] = ['OWNER', 'CONTRIBUTOR', 'READ_ONLY'];
  const members = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['members', project.id],
      enabled: owner,
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listMembers(project.id, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  async function perform(
    task: () => Promise<unknown>,
    success: string,
    failure?: (reason: unknown) => string | undefined,
  ) {
    busy = true;
    error = '';
    notice = '';
    try {
      await task();
      await query.invalidateQueries();
      notice = success;
    } catch (reason) {
      error = failure?.(reason) ?? explain(reason);
    } finally {
      busy = false;
    }
  }
  const memberName = (member: Awaited<ReturnType<typeof api.listMembers>>['items'][number]) =>
    member.display_name ?? member.username ?? member.user_id;
  const addMemberError = (reason: unknown) => {
    if (reason instanceof ApiError && reason.code === 'invalid_member')
      return 'No account matches that exact username. Check the spelling and ask the researcher to register first.';
    if (reason instanceof ApiError && reason.status === 409)
      return 'That account is already a member of this project.';
  };
  const ownerChangeError = (reason: unknown) => {
    if (reason instanceof ApiError && reason.status === 409)
      return 'Every project must retain at least one owner. Promote another member before changing this owner.';
  };
</script>

<header class="settings-header">
  <h1>Project settings</h1>
  <p>Manage project details, access, and lifecycle.</p>
</header>
{#if !owner}<p>Only project owners can manage settings and membership.</p>{:else}
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}{#if notice}<p
      role="status"
    >
      {notice}
    </p>{/if}
  <div class="settings-stack">
    <section class="settings-section" aria-labelledby="project-details-heading">
      <div class="section-heading">
        <h2 id="project-details-heading">Project details</h2>
        <p>Name, description, and who can read this project.</p>
      </div>
      <form
        class="details-form"
        onsubmit={async (e) => {
          e.preventDefault();
          if (
            visibility !== project.visibility &&
            !(await confirmation.ask(
              visibility === 'PUBLIC'
                ? 'Make this project public? Anyone will be able to read its saved research.'
                : 'Make this project private? Previously downloaded research and separately published Library releases cannot be retracted.',
            ))
          )
            return;
          void perform(
            () =>
              api.updateProject(project.id, {
                name: name.trim(),
                description,
                ...(visibility !== project.visibility ? { visibility } : {}),
              }),
            'Settings saved.',
          );
        }}
      >
        <Field.Label>Name<Input required maxlength={200} bind:value={name} /></Field.Label
        ><Field.Label>Description<Textarea bind:value={description}></Textarea></Field.Label>
        <Field.Label
          >Visibility<NativeSelect bind:value={visibility}>
            <option value="PUBLIC">Public</option>
            <option value="PRIVATE">Private</option>
          </NativeSelect></Field.Label
        ><Button type="submit" disabled={busy}>Save settings</Button>
      </form>
      <p class="visibility-note">
        {project.visibility === 'PUBLIC'
          ? 'Project details and saved research are public immediately. Membership controls writing, not reading.'
          : 'Only project members can read this project and its saved research.'}
      </p>
    </section>
    <section class="settings-section" aria-labelledby="members-heading">
      <div class="section-heading">
        <h2 id="members-heading">Members</h2>
        <p>Invite registered researchers and manage their roles.</p>
      </div>
      {#if $members.isError}<Alert.Root variant="destructive" role="alert"
          >{explain($members.error)}</Alert.Root
        >
        <Button type="button" onclick={() => $members.refetch()}>Retry</Button>{/if}
      <ul class="member-list">
        {#each $members.data?.pages.flatMap((p) => p.items) ?? [] as member (member.user_id)}<li>
            <div class="member-identity">
              <strong>{memberName(member)}</strong>
              {#if member.display_name && member.username}<small>@{member.username}</small>
              {:else if !member.display_name && !member.username}<small>{member.user_id}</small
                >{/if}
            </div>
            <div class="member-actions">
              <Field.Label
                >Role<NativeSelect
                  value={member.role}
                  disabled={busy}
                  onchange={(e) =>
                    void perform(
                      () =>
                        api.updateMember(project.id, member.user_id, e.currentTarget.value as Role),
                      'Role updated.',
                      ownerChangeError,
                    )}
                  >{#each roles as value (value)}<option>{value}</option>{/each}</NativeSelect
                ></Field.Label
              ><Button
                type="button"
                variant="outline"
                disabled={busy}
                onclick={async () => {
                  if (await confirmation.ask('Remove this member’s project access?'))
                    void perform(
                      () => api.removeMember(project.id, member.user_id),
                      'Member removed.',
                      ownerChangeError,
                    );
                }}>Remove</Button
              >
            </div>
          </li>{/each}
      </ul>
      {#if $members.hasNextPage}<Button type="button" onclick={() => $members.fetchNextPage()}
          >Load more members</Button
        >{/if}
      <form
        class="add-member-form"
        onsubmit={(e) => {
          e.preventDefault();
          void perform(
            async () => {
              await api.addMember(project.id, {
                username: username.trim().toLowerCase(),
                role,
              });
              username = '';
            },
            'Member added.',
            addMemberError,
          );
        }}
      >
        <h3>Add a collaborator</h3>
        <p class="muted">
          Enter the exact username of a registered Polycolab account. Account search and suggestions
          are intentionally unavailable.
        </p>
        <div class="add-member-fields">
          <Field.Label
            >Exact username<Input
              required
              minlength={3}
              maxlength={80}
              autocapitalize="none"
              autocomplete="off"
              bind:value={username}
            /></Field.Label
          ><Field.Label
            >Member role<NativeSelect bind:value={role}
              >{#each roles as value (value)}<option>{value}</option>{/each}</NativeSelect
            ></Field.Label
          >
        </div>
        <Button type="submit" disabled={busy}>Add member</Button>
      </form>
    </section>
    <section class="settings-section lifecycle-section" aria-labelledby="lifecycle-heading">
      <div class="section-heading">
        <h2 id="lifecycle-heading">Project lifecycle</h2>
        <p>Archive to pause contributions, or permanently delete the project.</p>
      </div>
      <div class="lifecycle-actions">
        <Button
          type="submit"
          variant="outline"
          class=""
          disabled={busy}
          onclick={() =>
            perform(
              () => api.updateProject(project.id, { archived: !project.archived_at }),
              'Lifecycle updated.',
            )}>{project.archived_at ? 'Unarchive project' : 'Archive project'}</Button
        ><Button
          type="submit"
          variant="destructive"
          class=""
          disabled={busy}
          onclick={async () => {
            if (
              await confirmation.ask(`Permanently delete ${project.name}? This cannot be undone.`)
            )
              void perform(async () => {
                await api.deleteProject(project.id);
                await goto('/');
              }, 'Project deleted.');
          }}>Delete permanently</Button
        >
      </div>
    </section>
  </div>{/if}

<ConfirmAction {confirmation} />

<style>
  .settings-header {
    margin-bottom: 24px;
  }
  .settings-header h1 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
  }
  .settings-header p,
  .section-heading p {
    margin: 5px 0 0;
    color: var(--muted-foreground);
    font-size: 13px;
    line-height: 1.5;
  }
  .settings-stack {
    display: grid;
    gap: 16px;
    max-width: 720px;
  }
  .settings-section {
    min-width: 0;
    padding: 20px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--panel);
  }
  .section-heading {
    margin-bottom: 20px;
  }
  .section-heading h2 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }
  .details-form,
  .add-member-form {
    display: grid;
    gap: 14px;
  }
  .details-form :global(button),
  .add-member-form :global(button) {
    justify-self: start;
  }
  .visibility-note {
    margin: 16px 0 0;
    color: var(--muted-foreground);
    font-size: 12px;
    line-height: 1.5;
  }
  .member-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .member-list li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 0;
    border-top: 1px solid var(--border);
  }
  .member-identity {
    display: grid;
    gap: 2px;
    min-width: 0;
  }
  .member-identity strong {
    overflow-wrap: anywhere;
    font-size: 13px;
    font-weight: 500;
  }
  .member-identity small {
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .member-actions {
    display: flex;
    align-items: end;
    gap: 8px;
    flex: 0 0 auto;
  }
  .member-actions :global(label) {
    min-width: 126px;
    font-size: 12px;
  }
  .add-member-form {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
  }
  .add-member-form h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }
  .add-member-form p {
    margin: -8px 0 0;
    font-size: 12px;
    line-height: 1.5;
  }
  .add-member-fields {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(140px, 0.55fr);
    gap: 12px;
  }
  .lifecycle-section {
    background: var(--panel-muted);
  }
  .lifecycle-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  @media (max-width: 600px) {
    .settings-section {
      padding: 16px;
    }
    .member-list li,
    .member-actions {
      flex-wrap: wrap;
    }
    .add-member-fields {
      grid-template-columns: 1fr;
    }
  }
</style>
