<template>
  <section class="page" data-module="fire">
    <header class="page-head">
      <div>
        <h2>消防设施检验台账</h2>
        <p class="page-desc">按场站登记灭火器等消防设施的数量、检验日期、压力表读数与下次检验月份，到期未检整批挑出、整批检验。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记消防设施</button>
        <button class="btn" type="button" @click="exportRows">导出台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ warn: item.warn }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>设施编号</span>
        <input v-model="filters.keyword" placeholder="按设施编号检索" />
      </label>
      <label class="filter-item">
        <span>所属场站</span>
        <select v-model="filters.station">
          <option value="">全部场站</option>
          <option v-for="name in stations" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>到期状态</span>
        <select v-model="filters.overdue">
          <option value="">全部</option>
          <option value="true">只看到期未检</option>
          <option value="false">只看在检</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="bulk-bar">
      <label class="check-all">
        <input ref="selectAllBox" type="checkbox" :checked="allChecked" @change="toggleAll" />
        全选当前结果（{{ rows.length }} 条）
      </label>
      <span class="bulk-tip">已勾选 {{ selectedIds.size }} 条</span>
      <button class="btn primary" type="button" :disabled="!selectedIds.size" @click="openBatch">
        批量提交检验（{{ selectedIds.size }}）
      </button>
      <button class="btn ghost" type="button" :disabled="!selectedIds.size" @click="selectedIds.clear()">清空勾选</button>
      <span v-if="selectError" class="error-text">{{ selectError }}</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">选择</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-overdue': isOverdueRow(row) }">
          <td class="col-check">
            <input type="checkbox" :checked="selectedIds.has(Number(row.id))" @change="toggleRow(Number(row.id))" />
          </td>
          <td v-for="column in columns" :key="column">
            <span v-if="column === '检验状态'" :class="isOverdueRow(row) ? 'tag tag-overdue' : 'tag tag-ok'">
              {{ isOverdueRow(row) ? '到期未检' : '正常' }}
            </span>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的消防设施</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条消防设施记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 批量检验弹窗 -->
    <div v-if="batchOpen" class="modal-mask" @click.self="closeBatch">
      <div class="modal">
        <header class="modal-head">
          <h3>批量提交检验结果</h3>
          <button class="link" type="button" @click="closeBatch">关闭</button>
        </header>
        <p class="modal-desc">
          场站：<strong>{{ batchStation }}</strong> · 批次号：{{ batchNo }}
          <span class="muted">（同一批次重复提交不会多出记录）</span>
        </p>
        <div class="form-grid">
          <label class="form-item">
            <span>检验日期 *</span>
            <input v-model="batchForm.inspectDate" type="date" />
          </label>
          <label class="form-item">
            <span>下次检验月份 *</span>
            <input v-model="batchForm.nextMonth" type="month" />
          </label>
        </div>
        <p class="range-hint">压力表读数合理范围：{{ pressureMin.toFixed(2) }} ~ {{ pressureMax.toFixed(2) }} MPa，超出范围只拦对应条目。</p>

        <table class="data-table batch-table">
          <thead>
            <tr>
              <th>设施编号</th><th>安装位置</th><th>上次检验日期</th>
              <th>压力表读数(MPa)</th><th>灭火器数量</th><th>提交结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in batchRows" :key="String(row.id)">
              <td>{{ row['设施编号'] }}</td>
              <td>{{ row['安装位置'] ?? '—' }}</td>
              <td>{{ row['上次检验日期'] ?? '—' }}</td>
              <td>
                <input
                  v-model.number="itemInputs[Number(row.id)].pressure"
                  class="cell-input"
                  type="number"
                  step="0.01"
                  :disabled="succeededIds.has(Number(row.id))"
                />
              </td>
              <td>
                <input
                  v-model.number="itemInputs[Number(row.id)].count"
                  class="cell-input"
                  type="number"
                  min="1"
                  :disabled="succeededIds.has(Number(row.id))"
                />
              </td>
              <td>
                <span v-if="itemResults[Number(row.id)]" :class="itemResults[Number(row.id)].ok ? 'tag tag-ok' : 'tag tag-overdue'">
                  {{ itemResults[Number(row.id)].ok ? '成功' : '失败' }}：{{ itemResults[Number(row.id)].message }}
                </span>
                <span v-else class="muted">待提交</span>
              </td>
            </tr>
          </tbody>
        </table>

        <footer class="modal-foot">
          <span v-if="batchSummary" class="batch-summary">{{ batchSummary }}</span>
          <span v-if="batchError" class="error-text">{{ batchError }}</span>
          <span class="foot-spacer" />
          <button class="btn" type="button" @click="closeBatch">完成</button>
          <button class="btn primary" type="button" :disabled="submitting || !pendingRows.length" @click="submitBatch">
            {{ succeededIds.size ? '修正后重新提交失败项' : '提交检验结果' }}
            <template v-if="pendingRows.length">（{{ pendingRows.length }} 条）</template>
          </button>
        </footer>
      </div>
    </div>

    <!-- 登记设施弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <header class="modal-head">
          <h3>登记消防设施</h3>
          <button class="link" type="button" @click="createOpen = false">关闭</button>
        </header>
        <div class="form-grid form-grid-2">
          <label class="form-item">
            <span>设施编号 *</span>
            <input v-model="createForm.facilityNo" placeholder="如 FIRE-0008" />
          </label>
          <label class="form-item">
            <span>所属场站 *</span>
            <input v-model="createForm.station" list="fire-stations" placeholder="选择或输入场站" />
            <datalist id="fire-stations">
              <option v-for="name in stations" :key="name" :value="name" />
            </datalist>
          </label>
          <label class="form-item">
            <span>设施类型 *</span>
            <input v-model="createForm.kind" placeholder="如 手提式干粉灭火器" />
          </label>
          <label class="form-item">
            <span>安装位置</span>
            <input v-model="createForm.location" placeholder="如 升压站一楼大厅" />
          </label>
          <label class="form-item">
            <span>灭火器数量 *</span>
            <input v-model.number="createForm.count" type="number" min="1" />
          </label>
          <label class="form-item">
            <span>上次检验日期 *</span>
            <input v-model="createForm.lastDate" type="date" />
          </label>
          <label class="form-item">
            <span>压力表读数(MPa) *</span>
            <input v-model.number="createForm.pressure" type="number" step="0.01" />
          </label>
          <label class="form-item">
            <span>下次检验月份 *</span>
            <input v-model="createForm.nextMonth" type="month" />
          </label>
        </div>
        <footer class="modal-foot">
          <span v-if="createMessage" :class="createOk ? '' : 'error-text'">{{ createMessage }}</span>
          <span class="foot-spacer" />
          <button class="btn primary" type="button" :disabled="creating" @click="submitCreate">确认登记</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Filters = { keyword: string; station: string; overdue: string }

const ENDPOINT = '/api/fire'
const columns = ["设施编号", "所属场站", "设施类型", "安装位置", "灭火器数量", "上次检验日期", "压力表读数", "下次检验月份", "检验状态"]
const pressureMin = 1.00
const pressureMax = 1.40

const rows = ref<Row[]>([])
const total = ref(0)
const stations = ref<string[]>([])
const errorMessage = ref('')
const filters = ref<Filters>({ keyword: '', station: '', overdue: '' })
const selectedIds = ref<Set<number>>(new Set())
const selectError = ref('')

const stats = ref([
  { label: '设施总数', value: 0, warn: false },
  { label: '到期未检', value: 0, warn: true },
  { label: '覆盖场站', value: 0, warn: false },
  { label: '累计检验记录', value: 0, warn: false },
])

function isOverdueRow(row: Row): boolean {
  return Boolean(row.pending) || row.status === '到期未检'
}

const allChecked = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.has(Number(row.id))))
const someChecked = computed(() => !allChecked.value && rows.value.some((row) => selectedIds.value.has(Number(row.id))))

// 全选框的半选状态没有直接的属性绑定写法，用 ref + watcher 同步 indeterminate。
const selectAllBox = ref<HTMLInputElement | null>(null)
watch([someChecked, rows, selectedIds], async () => {
  await nextTick()
  if (selectAllBox.value) {
    selectAllBox.value.indeterminate = someChecked.value
  }
}, { deep: true })

function toggleRow(id: number) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selectedIds.value = next
  selectError.value = ''
}

function toggleAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedIds.value = checked ? new Set(rows.value.map((row) => Number(row.id))) : new Set()
  selectError.value = ''
}

function resetFilters() {
  filters.value = { keyword: '', station: '', overdue: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---- 批量检验 ----
const batchOpen = ref(false)
const batchRows = ref<Row[]>([])
const batchStation = ref('')
const batchNo = ref('')
const batchForm = ref({ inspectDate: '', nextMonth: '' })
const itemInputs = ref<Record<number, { pressure: number | null; count: number | null }>>({})
const itemResults = ref<Record<number, { ok: boolean; message: string }>>({})
const succeededIds = ref<Set<number>>(new Set())
const batchSummary = ref('')
const batchError = ref('')
const submitting = ref(false)

const pendingRows = computed(() => batchRows.value.filter((row) => !succeededIds.value.has(Number(row.id))))

function todayISO(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function shiftMonth(value: string, delta: number): string {
  const [yearText, monthText] = value.split('-')
  const date = new Date(Number(yearText), Number(monthText) - 1 + delta, 1)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

function makeBatchNo(): string {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const rand = Math.random().toString(36).slice(2, 8).toUpperCase()
  return `BATCH-${stamp}-${rand}`
}

function openBatch() {
  selectError.value = ''
  const picked = rows.value.filter((row) => selectedIds.value.has(Number(row.id)))
  if (!picked.length) {
    selectError.value = '请先勾选需要检验的设施'
    return
  }
  const stationNames = [...new Set(picked.map((row) => String(row['所属场站'] ?? '')))]
  if (stationNames.length > 1) {
    selectError.value = `勾选的设施分属 ${stationNames.join('、')}，一次只能提交同一场站的设施，请按场站分批`
    return
  }
  batchRows.value = picked
  batchStation.value = stationNames[0]
  batchNo.value = makeBatchNo()
  const today = todayISO()
  batchForm.value = { inspectDate: today, nextMonth: shiftMonth(today.slice(0, 7), 6) }
  itemInputs.value = {}
  itemResults.value = {}
  succeededIds.value = new Set()
  batchSummary.value = ''
  batchError.value = ''
  for (const row of picked) {
    itemInputs.value[Number(row.id)] = {
      pressure: Number(row['压力表读数']) || null,
      count: Number(row['灭火器数量']) || null,
    }
  }
  batchOpen.value = true
}

function closeBatch() {
  batchOpen.value = false
  selectedIds.value = new Set()
  void reload()
}

async function submitBatch() {
  batchError.value = ''
  if (!batchForm.value.inspectDate) {
    batchError.value = '请填写检验日期'
    return
  }
  if (!batchForm.value.nextMonth) {
    batchError.value = '请填写下次检验月份'
    return
  }
  const items = pendingRows.value.map((row) => {
    const id = Number(row.id)
    const input = itemInputs.value[id]
    // 灭火器数量留空时不传，后端沿用台账原值；填 0 仍会被拦下提示。
    const count = input?.count === null || Number.isNaN(input?.count as number) ? null : input?.count
    return {
      facility_id: id,
      pressure: input?.pressure,
      extinguisher_count: count ?? null,
    }
  })
  if (items.some((item) => typeof item.pressure !== 'number' || Number.isNaN(item.pressure))) {
    batchError.value = '请为每条设施填写数字格式的压力表读数'
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/inspections/batch`, {
      method: 'POST',
      body: JSON.stringify({
        batch_no: batchNo.value,
        station: batchStation.value,
        inspect_date: batchForm.value.inspectDate,
        next_month: batchForm.value.nextMonth,
        items,
      }),
    })
    const payload = await response.json()
    if (!response.ok) {
      batchError.value = payload.detail ? String(payload.detail) : '整批提交被拒绝，请检查后重试'
      return
    }
    for (const result of payload.results ?? []) {
      itemResults.value[Number(result.facility_id)] = { ok: Boolean(result.ok), message: String(result.message) }
      if (result.ok && !result.duplicated) {
        succeededIds.value = new Set(succeededIds.value).add(Number(result.facility_id))
      }
    }
    const dupText = payload.duplicated ? '（重复提交，未新增记录）' : ''
    batchSummary.value = `${payload.message}${dupText}`
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量检验提交失败'
  } finally {
    submitting.value = false
  }
}

// ---- 登记设施 ----
const createOpen = ref(false)
const creating = ref(false)
const createMessage = ref('')
const createOk = ref(false)
const createForm = ref({
  facilityNo: '', station: '', kind: '', location: '',
  count: null as number | null, lastDate: '', pressure: null as number | null, nextMonth: '',
})

function openCreate() {
  createMessage.value = ''
  createOk.value = false
  createForm.value = {
    facilityNo: '', station: '', kind: '', location: '',
    count: null, lastDate: todayISO(), pressure: 1.2, nextMonth: shiftMonth(todayISO().slice(0, 7), 6),
  }
  createOpen.value = true
}

async function submitCreate() {
  createMessage.value = ''
  const form = createForm.value
  const values: Record<string, string | number> = {
    设施编号: form.facilityNo,
    所属场站: form.station,
    设施类型: form.kind,
    安装位置: form.location,
    灭火器数量: form.count ?? '',
    上次检验日期: form.lastDate,
    压力表读数: form.pressure ?? '',
    下次检验月份: form.nextMonth,
  }
  creating.value = true
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createOk.value = false
      createMessage.value = payload.message ? String(payload.message) : '登记失败'
      return
    }
    createOk.value = true
    createMessage.value = '消防设施已登记'
    createOpen.value = false
    await Promise.all([reload(), reloadStats(), reloadStations()])
  } catch (error) {
    createOk.value = false
    createMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = await response.json()
    stats.value[0].value = data.total ?? 0
    stats.value[1].value = data.overdue ?? 0
    stats.value[2].value = data.stations ?? 0
    stats.value[3].value = data.inspections ?? 0
  } catch {
    // 统计卡片读取失败时保留旧值，不打断列表操作
  }
}

async function reloadStations() {
  try {
    const response = await request(`${ENDPOINT}/stations`)
    if (response.ok) {
      stations.value = (await response.json()).items ?? []
    }
  } catch {
    // 场站下拉读取失败时保留已加载的选项
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.station) query.set('station', filters.value.station)
  if (filters.value.overdue) query.set('overdue', filters.value.overdue)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('消防设施列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 清理掉已不在当前筛选结果里的勾选
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => visibleIds.has(id)))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防设施列表读取失败'
  }
}

onMounted(async () => {
  await Promise.all([reload(), reloadStats(), reloadStations()])
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.warn { color: #b42318; }
.col-check { width: 44px; text-align: center; }
.bulk-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13px; }
.check-all { display: flex; align-items: center; gap: 6px; }
.bulk-tip { color: var(--muted); }
.bulk-bar .btn:disabled { opacity: 0.5; cursor: not-allowed; }
.row-overdue { background: #fff5f5; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.tag-ok { background: #e7f6ec; color: #1d7a3f; }
.tag-overdue { background: #fdecec; color: #b42318; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal { width: 880px; max-width: 94vw; max-height: 88vh; overflow: auto; background: #fff; border-radius: 10px; padding: 18px 20px; }
.modal-head { display: flex; justify-content: space-between; align-items: center; }
.modal-head h3 { margin: 0; font-size: 16px; }
.modal-desc { font-size: 13px; }
.muted { color: var(--muted); }
.range-hint { font-size: 12px; color: var(--muted); margin: 4px 0 10px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; margin: 10px 0; }
.form-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input, .form-item select { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.batch-table { margin: 8px 0; }
.cell-input { width: 96px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; }
.modal-foot { display: flex; align-items: center; gap: 10px; margin-top: 12px; font-size: 13px; }
.foot-spacer { flex: 1; }
.batch-summary { color: #1d7a3f; }
</style>
