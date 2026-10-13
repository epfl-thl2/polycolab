<script lang="ts">
  import { tick } from 'svelte';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { contributionCalendar, historyDateLabel } from '../lib/contribution-history';

  let {
    counts,
    year,
    selectedDay,
    loaded,
    busy,
    onYear,
    onDay,
  }: {
    counts: ReadonlyMap<string, number>;
    year: number;
    selectedDay?: string;
    loaded: boolean;
    busy: boolean;
    onYear: (year: number) => void;
    onDay: (day: string) => void;
  } = $props();
  let calendar = $state<HTMLDivElement>();
  const currentYear = new Date().getUTCFullYear();
  const years = $derived(
    [
      ...new Set([
        currentYear,
        year,
        ...Array.from(counts.keys(), (day) => Number(day.slice(0, 4))),
      ]),
    ].sort((a, b) => b - a),
  );
  const days = $derived(contributionCalendar(year, counts));
  const total = $derived(days.reduce((sum, day) => sum + day.count, 0));
  $effect(() => {
    const day = selectedDay ?? days.filter((day) => day.count > 0).at(-1)?.day;
    const element = calendar;
    if (!element || !day) return;
    void tick().then(() => {
      const cell = element.querySelector<HTMLElement>(`[data-day="${day}"]`);
      if (cell)
        element.scrollLeft +=
          cell.getBoundingClientRect().left -
          element.getBoundingClientRect().left -
          element.clientWidth / 2;
    });
  });
  function label(day: (typeof days)[number]) {
    return `${historyDateLabel(day.day)}: ${day.count} loaded contribution${day.count === 1 ? '' : 's'}`;
  }
</script>

<section class="contribution-history" aria-labelledby="history-title" aria-busy={busy}>
  <div class="history-heading">
    <div>
      <h2 id="history-title">Contribution history</h2>
      <p role="status">
        {#if loaded}{total} loaded public contribution{total === 1 ? '' : 's'}{:else}{busy
            ? 'Loading contribution history…'
            : 'Contribution history unavailable'}{/if}
      </p>
    </div>
    <NativeSelect
      aria-label="Contribution year"
      value={String(year)}
      onchange={(event) => onYear(Number(event.currentTarget.value))}
    >
      {#each years as option (option)}<option value={String(option)}>{option}</option>{/each}
    </NativeSelect>
  </div>
  {#if loaded}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex (The scrollable calendar needs keyboard focus for horizontal scrolling.) -->
    <div
      bind:this={calendar}
      class="calendar-scroll"
      role="region"
      aria-label="Yearly contribution calendar, scroll horizontally on small screens"
      tabindex="0"
    >
      <div class="calendar" style={`--weeks: ${days.at(-1)?.column ?? 53}`}>
        <div class="weekdays" aria-hidden="true">
          <span>Mon</span><span>Wed</span><span>Fri</span>
        </div>
        <div class="days">
          {#each days as day (day.day)}
            {#if day.month}<span
                class="month"
                style={`grid-column: ${day.column}; grid-row: 1`}
                aria-hidden="true">{day.month}</span
              >{/if}
            {#if day.count}
              <button
                type="button"
                class="day"
                data-day={day.day}
                data-level={day.level}
                style={`grid-column: ${day.column}; grid-row: ${day.row}`}
                title={label(day)}
                aria-label={label(day)}
                aria-pressed={selectedDay === day.day}
                onclick={() => onDay(day.day)}
              ></button>
            {:else}
              <span
                class="day"
                data-level="0"
                data-day={day.day}
                style={`grid-column: ${day.column}; grid-row: ${day.row}`}
                title={label(day)}
                aria-hidden="true"
              ></span>
            {/if}
          {/each}
        </div>
      </div>
    </div>
    <div class="mobile-day-picker">
      <NativeSelect
        aria-label="Contribution day"
        value={selectedDay ?? ''}
        onchange={(event) => onDay(event.currentTarget.value)}
      >
        <option value="">All dates</option>
        {#each days
          .filter((day) => day.count > 0 || day.day === selectedDay)
          .toReversed() as day (day.day)}<option value={day.day}
            >{historyDateLabel(day.day)} · {day.count}</option
          >{/each}
      </NativeSelect>
    </div>
    <div class="history-key">
      <span>Loaded public activity · UTC</span>
      <div
        class="legend"
        aria-label="Contribution intensity: blank means no loaded contributions; shades indicate 1, 2 to 3, 4 to 7, or 8 or more"
      >
        <span>Less</span>{#each [0, 1, 2, 3, 4] as level (level)}<span
            class="day"
            data-level={level}
            aria-hidden="true"
          ></span>{/each}<span>More</span>
      </div>
    </div>
  {/if}
</section>

<style>
  .contribution-history {
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 22px 24px;
    margin-bottom: 36px;
    min-width: 0;
  }
  .history-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 22px;
  }
  h2 {
    margin: 0;
    font-size: 18px;
  }
  p {
    margin: 6px 0 0;
    color: var(--muted-foreground);
    font-size: 12px;
    line-height: 1.6;
  }
  .history-heading :global(select) {
    width: auto;
    flex-shrink: 0;
  }
  .calendar-scroll {
    overflow-x: auto;
    padding: 4px;
    margin: -4px;
  }
  .calendar {
    display: flex;
    gap: 8px;
    min-width: max-content;
  }
  .weekdays {
    display: grid;
    grid-template-rows: 20px repeat(7, 13px);
    gap: 4px;
    font-size: 10px;
    color: var(--muted-foreground);
  }
  .weekdays span:nth-child(1) {
    grid-row: 3;
  }
  .weekdays span:nth-child(2) {
    grid-row: 5;
  }
  .weekdays span:nth-child(3) {
    grid-row: 7;
  }
  .days {
    display: grid;
    grid-template-columns: repeat(var(--weeks), 13px);
    grid-template-rows: 20px repeat(7, 13px);
    gap: 4px;
  }
  .month {
    color: var(--muted-foreground);
    font-size: 10px;
    align-self: start;
  }
  .day {
    display: block;
    width: 13px;
    height: 13px;
    padding: 0;
    border-radius: 3px;
    border: 1px solid color-mix(in srgb, var(--foreground) 9%, transparent);
    background: var(--accent);
  }
  .day[data-level='1'] {
    background: color-mix(in srgb, var(--brand) 25%, var(--background));
  }
  .day[data-level='2'] {
    background: color-mix(in srgb, var(--brand) 45%, var(--background));
  }
  .day[data-level='3'] {
    background: color-mix(in srgb, var(--brand) 70%, var(--background));
  }
  .day[data-level='4'] {
    background: var(--brand);
  }
  button.day {
    cursor: pointer;
  }
  button.day:hover,
  .day[aria-pressed='true'] {
    outline: 2px solid var(--foreground);
    outline-offset: 1px;
  }
  .calendar-scroll:focus-visible,
  button.day:focus-visible {
    outline: 2px solid var(--brand);
    outline-offset: 2px;
  }
  .mobile-day-picker {
    display: none;
  }
  .history-key {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 18px;
    font-size: 11px;
    color: var(--muted-foreground);
  }
  .legend {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .legend span:first-child {
    margin-right: 4px;
  }
  .legend span:last-child {
    margin-left: 4px;
  }
  @media (max-width: 540px) {
    .mobile-day-picker {
      display: block;
      margin-top: 16px;
    }
    .mobile-day-picker :global([data-slot='native-select-wrapper']) {
      width: 100%;
    }
    .mobile-day-picker :global(select) {
      width: 100%;
      min-height: 44px;
    }
    .contribution-history {
      padding: 18px 16px;
      margin-bottom: 28px;
    }
    .history-heading {
      align-items: start;
    }
    .history-heading :global(select) {
      min-height: 44px;
    }
  }
</style>
