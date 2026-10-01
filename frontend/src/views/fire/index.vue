<template>
  <section class="page" data-module="fire">
    <header class="page-head">
      <div>
        <h2>消防设施检验台账</h2>
        <p class="page-desc">按场站登记消防设施的灭火器数量、检验日期、压力表读数与下次检验月份；到期未检整批挑出，同场站设施可勾选后一次提交检验结果。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记消防设施</button>
        <button class="btn" type="button" @click="exportRows">导出消防设施清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="{ clickable: item.filter }" @click="item.filter && toggleOverdue()">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ 'warn-text': item.warn && item.value }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload()">
      <label class="filter-item">
        <span>设施编号/名称</span>
        <input v-model="filters.keyword" placeholder="按设施编号或名称检索" />
      </label>
      <label class="filter-item">
        <span>所属场站</span>
        <input v-model="filters.station" placeholder="按所属场站检索" />
      </label>
      <label class="filter-item">
        <span>设施状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn" :class="{ primary: filters.overdue === 'true' }" type="button" @click="toggleOverdue">到期未检</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selectedRows.length" class="selected-bar">
      <span>已选 {{ selectedRows.length }} 条「{{ selectedStation }}」的设施，检验结果将按同一批次提交，单条失败不影响其他设施入账。</span>
      <div class="row-actions">
        <button class="btn primary" type="button" @click="openBatch">批量提交检验</button>
        <button class="btn ghost" type="button" @click="clearSelection">清空选择</button>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col"></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>检验提醒</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="isSelected(row)"
              :disabled="!isSelected(row) && !canSelect(row)"
              :title="selectHint(row)"
              @change="toggleRow(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row.overdue" class="badge warn">到期未检</span>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="row.status === '已作废'"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无消防设施数据，可先登记消防设施</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条消防设施记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="batchVisible" class="modal-mask" @click.self="closeBatch">
      <div class="modal">
        <header class="modal-head">
          <h3>批量提交检验结果</h3>
          <button class="link" type="button" @click="closeBatch">关闭</button>
        </header>
        <div class="modal-body">
          <div class="form-grid">
            <label class="filter-item">
              <span>批次号（重复提交不会多出记录）</span>
              <input v-model="batchId" />
            </label>
            <label class="filter-item">
              <span>检验日期</span>
              <input v-model="inspectDate" type="date" />
            </label>
            <label class="filter-item">
              <span>下次检验月份</span>
              <input v-model="nextMonth" type="month" />
            </label>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>设施编号</th>
                <th>设施名称</th>
                <th>压力表读数（MPa，{{ pressureRangeText }}）</th>
                <th>提交结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in selectedRows" :key="String(row.id)">
                <td>{{ row.设施编号 }}</td>
                <td>{{ row.设施名称 }}</td>
                <td>
                  <input v-model="pressures[row.id]" class="pressure-input" type="number" step="0.01" placeholder="如 1.20" />
                </td>
                <td>
                  <span v-if="resultOf(row)" :class="resultOf(row)?.ok ? 'ok-text' : 'error-text'">
                    {{ resultOf(row)?.message }}
                  </span>
                  <span v-else>待提交</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="batchMessage" class="batch-message">{{ batchMessage }}</p>
        </div>
        <footer class="modal-foot">
          <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
            {{ submitting ? '提交中…' : '提交检验结果' }}
          </button>
          <button class="btn ghost" type="button" @click="closeBatch">取消</button>
        </footer>
      </div>
    </div>

    <div v-if="createVisible" class="modal-mask" @click.self="createVisible = false">
      <div class="modal">
        <header class="modal-head">
          <h3>登记消防设施</h3>
          <button class="link" type="button" @click="createVisible = false">关闭</button>
        </header>
        <div class="modal-body">
          <div class="form-grid">
            <label v-for="field in createFields" :key="field.key" class="filter-item">
              <span>{{ field.label }}{{ field.required ? '（必填）' : '（选填）' }}</span>
              <input v-model="createForm[field.key]" :type="field.type" :placeholder="field.placeholder" />
            </label>
          </div>
          <p v-if="createError" class="error-text">{{ createError }}</p>
        </div>
        <footer class="modal-foot">
          <button class="btn primary" type="button" :disabled="creating" @click="submitCreate">
            {{ creating ? '登记中…' : '确认登记' }}
          </button>
          <button class="btn ghost" type="button" @click="createVisible = false">取消</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null> & { id: number }
type BatchItemResult = { id: number; ok: boolean; message: string }

const ENDPOINT = '/api/fire'
const columns = ['设施编号', '设施名称', '所属场站', '灭火器数量', '上次检验日期', '压力表读数', '下次检验月份', '设施状态']
const actions = ['作废设施']
const statuses = ['待检验', '检验合格', '已作废']
const pressureRangeText = '0.5~2.5'

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', station: '', status: '', overdue: '' })
const summary = ref({ total: 0, overdue: 0, inspected_this_month: 0, scrapped: 0 })

const stats = computed(() => [
  { label: '设施总数', value: summary.value.total, filter: false, warn: false },
  { label: '到期未检（点击筛选）', value: summary.value.overdue, filter: true, warn: true },
  { label: '本月检验入账', value: summary.value.inspected_this_month, filter: false, warn: false },
  { label: '已作废', value: summary.value.scrapped, filter: false, warn: false },
])

// ---- 勾选：同一批次只允许同一场站的设施 ----
const selectedIds = ref<number[]>([])
const selectedRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(row.id)))
const selectedStation = computed(() => String(selectedRows.value[0]?.['所属场站'] ?? ''))

function isSelected(row: Row) {
  return selectedIds.value.includes(row.id)
}

function canSelect(row: Row) {
  if (row.status === '已作废') return false
  if (!selectedStation.value) return true
  return String(row['所属场站']) === selectedStation.value
}

function selectHint(row: Row) {
  if (row.status === '已作废') return '已作废的设施不能登记检验'
  if (selectedStation.value && String(row['所属场站']) !== selectedStation.value) {
    return `已选择「${selectedStation.value}」的设施，同一批次只能提交同一场站`
  }
  return ''
}

function toggleRow(row: Row) {
  if (isSelected(row)) {
    selectedIds.value = selectedIds.value.filter((id) => id !== row.id)
  } else if (canSelect(row)) {
    selectedIds.value = [...selectedIds.value, row.id]
  }
}

function clearSelection() {
  selectedIds.value = []
}

// ---- 筛选与统计 ----
function toggleOverdue() {
  filters.value.overdue = filters.value.overdue === 'true' ? '' : 'true'
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', station: '', status: '', overdue: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---- 批量检验 ----
const batchVisible = ref(false)
const submitting = ref(false)
const batchId = ref('')
const inspectDate = ref('')
const nextMonth = ref('')
const pressures = ref<Record<number, string>>({})
const batchResults = ref<BatchItemResult[]>([])
const batchMessage = ref('')

function todayText() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function shiftMonth(dateText: string, months: number) {
  const date = new Date(`${dateText}T00:00:00`)
  date.setMonth(date.getMonth() + months)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

function openBatch() {
  batchId.value = `BAT-${Date.now()}`
  inspectDate.value = todayText()
  nextMonth.value = shiftMonth(inspectDate.value, 12)
  pressures.value = {}
  batchResults.value = []
  batchMessage.value = ''
  batchVisible.value = true
}

function closeBatch() {
  batchVisible.value = false
  batchResults.value = []
  batchMessage.value = ''
  clearSelection()
}

function resultOf(row: Row) {
  return batchResults.value.find((item) => item.id === row.id)
}

async function submitBatch() {
  if (submitting.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/inspect`, {
      method: 'POST',
      body: JSON.stringify({
        batch_id: batchId.value,
        inspect_date: inspectDate.value,
        next_month: nextMonth.value,
        items: selectedRows.value.map((row) => ({ id: row.id, pressure: pressures.value[row.id] ?? '' })),
      }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '批量检验提交失败，请稍后重试')
    }
    // 逐条展示成功或失败；批次号保持不变，修正失败条目后重交不会多出记录
    batchResults.value = payload.results ?? []
    batchMessage.value = payload.message ?? ''
    await Promise.all([reload(false), loadSummary()])
  } catch (error) {
    batchMessage.value = error instanceof Error ? error.message : '批量检验提交失败'
  } finally {
    submitting.value = false
  }
}

// ---- 登记设施 ----
const createVisible = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = ref<Record<string, string>>({})
const createFields = [
  { key: '设施名称', label: '设施名称', type: 'text', required: true, placeholder: '如 主控楼手提式干粉灭火器' },
  { key: '所属场站', label: '所属场站', type: 'text', required: true, placeholder: '如 风电场站样例1' },
  { key: '灭火器数量', label: '灭火器数量', type: 'number', required: true, placeholder: '正整数' },
  { key: '下次检验月份', label: '下次检验月份', type: 'month', required: true, placeholder: '' },
  { key: '上次检验日期', label: '上次检验日期', type: 'date', required: false, placeholder: '' },
  { key: '压力表读数', label: `压力表读数（MPa，${pressureRangeText}）`, type: 'number', required: false, placeholder: '如 1.20' },
]

function openCreate() {
  createForm.value = {}
  createError.value = ''
  createVisible.value = true
}

async function submitCreate() {
  if (creating.value) return
  creating.value = true
  createError.value = ''
  try {
    const values = Object.fromEntries(
      Object.entries(createForm.value).filter(([, value]) => String(value ?? '').trim() !== ''),
    )
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? payload.detail ?? '设施登记失败，请检查填写内容'
      return
    }
    createVisible.value = false
    await Promise.all([reload(false), loadSummary()])
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '设施登记失败'
  } finally {
    creating.value = false
  }
}

// ---- 单条动作 ----
async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '消防设施动作未生效，请稍后重试')
    }
    await Promise.all([reload(false), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防设施操作失败'
  }
}

// ---- 数据加载 ----
async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) {
      summary.value = await response.json()
    }
  } catch {
    // 统计卡片失败不阻塞列表
  }
}

async function reload(clear = true) {
  if (clear) clearSelection()
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value !== '')),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('消防设施列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消防设施列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
