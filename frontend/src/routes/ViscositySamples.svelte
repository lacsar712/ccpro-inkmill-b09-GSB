<script lang="ts">
  import { onMount } from 'svelte';
  import { api, downloadFile } from '../lib/api';
  import type { ExportCheck, Mill, ViscositySample, Workshop } from '../lib/types';

  let rows: ViscositySample[] = [];
  let mills: Mill[] = [];
  let workshops: Workshop[] = [];
  let error = '';
  let editingId: number | null = null;

  function nowLocal(): string {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  let form = {
    millId: '',
    sampledAt: nowLocal(),
    viscosityPaS: '10',
    tempC: '',
    notes: '',
  };

  // 导出筛选条件；export-check 与 export.csv 必须共用同一个 query string。
  let exportForm = { workshopId: '', millId: '', from: '', to: '' };
  let checkResult: ExportCheck | null = null;
  let confirmedQuery = '';
  let checking = false;
  let downloading = false;
  let exportError = '';

  async function load() {
    error = '';
    try {
      [rows, mills, workshops] = await Promise.all([
        api<ViscositySample[]>('/viscosity-samples'),
        api<Mill[]>('/mills'),
        api<Workshop[]>('/workshops'),
      ]);
      if (!form.millId && mills[0]) form.millId = String(mills[0].id);
    } catch (e) {
      error = e instanceof Error ? e.message : '加载失败';
    }
  }

  onMount(load);

  $: exportableMills = exportForm.workshopId
    ? mills.filter((m) => String(m.workshopId) === exportForm.workshopId)
    : mills;

  function millLabel(id: number): string {
    const m = mills.find((x) => x.id === id);
    return m ? `${m.millCode} (#${id})` : `#${id}`;
  }

  function reset() {
    form = {
      millId: mills[0] ? String(mills[0].id) : '',
      sampledAt: nowLocal(),
      viscosityPaS: '10',
      tempC: '',
      notes: '',
    };
    editingId = null;
  }

  function toLocalInput(iso: string): string {
    const d = new Date(iso.replace(' ', 'T'));
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  function edit(row: ViscositySample) {
    editingId = row.id;
    form = {
      millId: String(row.millId),
      sampledAt: toLocalInput(row.sampledAt),
      viscosityPaS: String(row.viscosityPaS),
      tempC: row.tempC != null ? String(row.tempC) : '',
      notes: row.notes || '',
    };
  }

  async function save() {
    error = '';
    const payload = {
      millId: Number(form.millId),
      sampledAt: form.sampledAt,
      viscosityPaS: Number(form.viscosityPaS),
      tempC: form.tempC === '' ? null : Number(form.tempC),
      notes: form.notes,
    };
    try {
      if (editingId) {
        await api(`/viscosity-samples/${editingId}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
      } else {
        await api('/viscosity-samples', { method: 'POST', body: JSON.stringify(payload) });
      }
      reset();
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '保存失败';
    }
  }

  async function remove(id: number) {
    if (!confirm('确认删除该粘度取样记录？')) return;
    try {
      await api(`/viscosity-samples/${id}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '删除失败';
    }
  }

  function invalidateCheck() {
    // 筛选一变，上一次对账结果即失效，必须重新对账后才能下载。
    checkResult = null;
    confirmedQuery = '';
    exportError = '';
  }

  function onWorkshopChange() {
    exportForm.millId = '';
    invalidateCheck();
  }

  function buildQuery(): string {
    const p = new URLSearchParams();
    if (exportForm.workshopId) p.set('workshopId', exportForm.workshopId);
    if (exportForm.millId) p.set('millId', exportForm.millId);
    if (exportForm.from) p.set('from', exportForm.from);
    if (exportForm.to) p.set('to', exportForm.to);
    const s = p.toString();
    return s ? `?${s}` : '';
  }

  async function runCheck() {
    exportError = '';
    if (exportForm.from && exportForm.to && exportForm.from > exportForm.to) {
      exportError = '起始时间不能晚于结束时间';
      return;
    }
    checking = true;
    const query = buildQuery();
    try {
      checkResult = await api<ExportCheck>(`/viscosity-samples/export-check${query}`);
      confirmedQuery = query;
    } catch (e) {
      checkResult = null;
      confirmedQuery = '';
      exportError = e instanceof Error ? e.message : '对账失败';
    } finally {
      checking = false;
    }
  }

  async function confirmDownload() {
    if (!checkResult || !confirmedQuery) return;
    downloading = true;
    exportError = '';
    try {
      // 直接复用时对账时的 query string，保证两次请求筛选完全一致。
      await downloadFile(`/viscosity-samples/export.csv${confirmedQuery}`, 'viscosity-samples.csv');
    } catch (e) {
      exportError = e instanceof Error ? e.message : '下载失败';
    } finally {
      downloading = false;
    }
  }
</script>

<header class="page-head">
  <h1>粘度取样</h1>
  <p>记录 Pa·s 粘度（必须 &gt; 0），配合温度与备注</p>
</header>

{#if error}
  <div class="err">{error}</div>
{/if}

<section class="panel">
  <h2>导出 CSV（先对账后下载）</h2>
  <p class="hint">时间按东八区解释；仅日期时结束日含当天全天。车间名由取样记录的研磨机归属车间确定。</p>
  <div class="fields">
    <div class="field">
      <label>车间
        <select bind:value={exportForm.workshopId} on:change={onWorkshopChange}>
          <option value="">全部车间</option>
          {#each workshops as w}
            <option value={String(w.id)}>{w.name}</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field">
      <label>研磨机
        <select bind:value={exportForm.millId} on:change={invalidateCheck}>
          <option value="">全部研磨机</option>
          {#each exportableMills as m}
            <option value={String(m.id)}>{m.millCode}</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field">
      <label>起始时间
        <input type="datetime-local" bind:value={exportForm.from} on:input={invalidateCheck} />
      </label>
    </div>
    <div class="field">
      <label>结束时间
        <input type="datetime-local" bind:value={exportForm.to} on:input={invalidateCheck} />
      </label>
    </div>
  </div>
  <div class="actions">
    <button class="btn-primary" on:click={runCheck} disabled={checking}>
      {checking ? '对账中…' : '对账'}
    </button>
    {#if checkResult}
      <button class="btn-ghost" on:click={confirmDownload} disabled={downloading}>
        {downloading ? '下载中…' : '确认下载 CSV'}
      </button>
    {/if}
  </div>

  {#if exportError}
    <div class="err">{exportError}</div>
  {/if}

  {#if checkResult}
    <div class="check-result">
      <div class="check-summary">
        <span>数据行数：<strong>{checkResult.rows}</strong></span>
        <span>粘度合计：<strong>{checkResult.sumViscosity.toFixed(4)}</strong> Pa·s</span>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>车间</th>
            <th>行数</th>
            <th>粘度合计 (Pa·s)</th>
          </tr>
        </thead>
        <tbody>
          {#each checkResult.byWorkshop as item}
            <tr>
              <td>{item.workshopName}</td>
              <td>{item.count}</td>
              <td>{item.sumViscosity.toFixed(4)}</td>
            </tr>
          {:else}
            <tr><td colspan="3">无匹配记录，CSV 将仅含表头</td></tr>
          {/each}
        </tbody>
      </table>
      <p class="hint">请核对以上行数与合计，确认无误后点击「确认下载 CSV」。</p>
    </div>
  {/if}
</section>

<section class="panel">
  <h2>{editingId ? '编辑取样' : '新增取样'}</h2>
  <div class="fields">
    <div class="field">
      <label>研磨机
        <select bind:value={form.millId}>
          {#each mills as m}
            <option value={String(m.id)}>{m.millCode}</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field"><label>取样时间<input type="datetime-local" bind:value={form.sampledAt} /></label></div>
    <div class="field"><label>粘度 Pa·s<input type="number" step="0.0001" min="0.0001" bind:value={form.viscosityPaS} /></label></div>
    <div class="field"><label>温度 ℃<input type="number" step="0.1" bind:value={form.tempC} /></label></div>
    <div class="field full"><label>备注<textarea rows="2" bind:value={form.notes} /></label></div>
  </div>
  <div class="actions">
    <button class="btn-primary" on:click={save}>{editingId ? '保存' : '创建'}</button>
    {#if editingId}
      <button class="btn-ghost" on:click={reset}>取消</button>
    {/if}
  </div>
</section>

<section class="panel">
  <table class="data-table">
    <thead>
      <tr>
        <th>ID</th>
        <th>研磨机</th>
        <th>取样时间</th>
        <th>Pa·s</th>
        <th>℃</th>
        <th>备注</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row}
        <tr>
          <td>{row.id}</td>
          <td>{millLabel(row.millId)}</td>
          <td>{row.sampledAt}</td>
          <td>{row.viscosityPaS}</td>
          <td>{row.tempC ?? '—'}</td>
          <td>{row.notes || '—'}</td>
          <td class="ops">
            <button class="link-btn" on:click={() => edit(row)}>编辑</button>
            <button class="link-btn danger" on:click={() => remove(row.id)}>删除</button>
          </td>
        </tr>
      {:else}
        <tr><td colspan="7">暂无数据</td></tr>
      {/each}
    </tbody>
  </table>
</section>

<style>
  .hint {
  margin: 4px 0 12px;
  font-size: 12px;
  opacity: 0.7;
  }

  .check-result {
  margin-top: 12px;
  }

  .check-summary {
  display: flex;
  gap: 24px;
  margin-bottom: 8px;
  }
</style>
