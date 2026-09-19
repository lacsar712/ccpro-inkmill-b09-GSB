<script lang="ts">
  import { onMount } from 'svelte';
  import { api, apiBlob } from '../lib/api';
  import type { Mill, ViscosityExportCheck, ViscositySample, Workshop } from '../lib/types';

  let rows: ViscositySample[] = [];
  let mills: Mill[] = [];
  let workshops: Workshop[] = [];
  let error = '';
  let editingId: number | null = null;

  // 导出筛选（与服务端 export-check / export.csv 完全一致的四个参数）
  let filter = { workshopId: '', millId: '', from: '', to: '' };
  let checkInfo: ViscosityExportCheck | null = null;
  let lastCheckKey: string | null = null;
  let checking = false;
  let downloading = false;
  let exportErr = '';

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

  // 选定车间后，研磨机下拉只列该车间下的机台
  $: millOptions = filter.workshopId
    ? mills.filter((m) => m.workshopId === Number(filter.workshopId))
    : mills;

  // 车间切换时清空已选机台，避免 workshopId/millId 矛盾
  function onWorkshopChange() {
    filter.millId = '';
  }

  // 对账与下载必须共用同一查询串，保证两次请求筛选条件完全一致
  function buildExportQuery(): string {
    const p = new URLSearchParams();
    if (filter.workshopId) p.set('workshopId', filter.workshopId);
    if (filter.millId) p.set('millId', filter.millId);
    if (filter.from) p.set('from', filter.from);
    if (filter.to) p.set('to', filter.to);
    const s = p.toString();
    return s ? `?${s}` : '';
  }

  $: checkStale = checkInfo !== null && buildExportQuery() !== lastCheckKey;

  async function checkExport() {
    exportErr = '';
    checking = true;
    checkInfo = null;
    lastCheckKey = null;
    const q = buildExportQuery();
    try {
      checkInfo = await api<ViscosityExportCheck>(`/viscosity-samples/export-check${q}`);
      lastCheckKey = q;
    } catch (e) {
      exportErr = e instanceof Error ? e.message : '对账失败';
    } finally {
      checking = false;
    }
  }

  async function confirmDownload() {
    const q = buildExportQuery();
    if (!checkInfo || q !== lastCheckKey) return; // 筛选已变更，必须重新对账
    exportErr = '';
    downloading = true;
    try {
      const blob = await apiBlob(`/viscosity-samples/export.csv${q}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'viscosity-samples.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      exportErr = e instanceof Error ? e.message : '下载失败';
    } finally {
      downloading = false;
    }
  }

  function millLabel(id: number): string {
    const m = mills.find((x) => x.id === id);
    return m ? `${m.millCode} (#${m.id})` : `#${id}`;
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
</script>

<header class="page-head">
  <h1>粘度取样</h1>
  <p>记录 Pa·s 粘度（必须 &gt; 0），配合温度与备注</p>
</header>

{#if error}
  <div class="err">{error}</div>
{/if}

<section class="panel">
  <h2>导出 CSV</h2>
  <p class="hint">先按当前筛选对账，确认行数与合计后再下载；CSV 由服务端生成。</p>
  <div class="fields">
    <div class="field">
      <label>车间
        <select bind:value={filter.workshopId} on:change={onWorkshopChange}>
          <option value="">全部车间</option>
          {#each workshops as w}
            <option value={String(w.id)}>{w.name}</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field">
      <label>研磨机
        <select bind:value={filter.millId}>
          <option value="">全部研磨机</option>
          {#each millOptions as m}
            <option value={String(m.id)}>{m.millCode} (#{m.id})</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field"><label>起始时间(东八区)<input type="datetime-local" bind:value={filter.from} /></label></div>
    <div class="field"><label>结束时间(东八区)<input type="datetime-local" bind:value={filter.to} /></label></div>
  </div>
  <div class="actions">
    <button class="btn-primary" on:click={checkExport} disabled={checking}>
      {checking ? '对账中…' : '对账'}
    </button>
    <button
      class="btn-ghost"
      on:click={confirmDownload}
      disabled={!checkInfo || checkStale || downloading}
    >
      {downloading ? '下载中…' : '确认并下载 CSV'}
    </button>
    {#if checkStale}
      <span class="stale">筛选已变更，请重新对账</span>
    {/if}
    {#if exportErr}
      <span class="err-inline">{exportErr}</span>
    {/if}
  </div>

  {#if checkInfo}
    <div class="check">
      <div class="check-line">
        <strong>{checkInfo.rows}</strong> 行，粘度合计 <strong>{checkInfo.sumViscosity.toFixed(4)}</strong> Pa·s
      </div>
      <table class="data-table">
        <thead>
          <tr><th>车间</th><th>行数</th><th>粘度合计</th></tr>
        </thead>
        <tbody>
          {#each checkInfo.byWorkshop as b}
            <tr>
              <td>{b.workshopName}</td>
              <td>{b.count}</td>
              <td>{b.sumViscosity.toFixed(4)}</td>
            </tr>
          {:else}
            <tr><td colspan="3">无匹配记录（CSV 将仅含表头）</td></tr>
          {/each}
        </tbody>
      </table>
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
