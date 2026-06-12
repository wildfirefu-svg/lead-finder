from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .apollo import ApolloClient
from .campaigns import CampaignOptions, run_campaign
from .config import settings
from .contact_enrichment import enrich_qualified_emails, verify_existing_qualified_emails
from .crm import crm_status, sync_verified_qualified
from .db import connect, latest_provider_usage, list_leads, stats, update_lead
from .evidence import parse_score_evidence, review_status_for_lead, score_reason_text
from .exporter import export_csv_bytes
from .hunter import HunterClient
from .query_catalog import PRODUCT_FAMILY_LABELS
from .recall import recall_report
from .requalify import RequalifyOptions, requalify_leads
from .security import sanitize_error
from .serper import SerperClient


ALLOWED_STATUSES = {"Discovered", "Enriched", "Qualified", "Rejected", "Error"}
SUPPORTED_REVIEWS = {"high_confidence", "needs_review", "suspected_supplier", "crawl_failed"}
WEB_PRODUCT_FAMILY_LABELS = {**PRODUCT_FAMILY_LABELS, "all": "全部产品族"}
PRODUCT_FAMILY_OPTIONS_HTML = "\n".join(
    f'            <option value="{value}">{label}</option>'
    for value, label in WEB_PRODUCT_FAMILY_LABELS.items()
)

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>玻纤外贸获客工作台</title>
  <style>
    :root {
      --ink: #17202a;
      --muted: #5d6775;
      --line: #cfd8df;
      --paper: #fbfcf7;
      --panel: #ffffff;
      --rail: #243447;
      --accent: #1d766f;
      --accent-2: #b85c38;
      --good: #256d3f;
      --warn: #9a5a14;
      --bad: #9b2c2c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: "Aptos", "Segoe UI", sans-serif;
    }
    header {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) minmax(0, 3fr);
      gap: 16px;
      align-items: end;
      padding: 22px 28px;
      background: var(--rail);
      color: #f8faf2;
      border-bottom: 4px solid var(--accent-2);
    }
    h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .subhead {
      margin-top: 4px;
      color: #c9d4dc;
      font-size: 13px;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    button, select, input {
      min-height: 34px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 4px;
      padding: 6px 9px;
      font: inherit;
      min-width: 0;
    }
    button {
      border-color: #8da0ad;
      background: #f6f8fa;
      cursor: pointer;
    }
    button:hover { background: #eaf0ef; border-color: var(--accent); }
    main { padding: 18px 28px 28px; }
    .campaign {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 12px;
      margin-bottom: 14px;
    }
    .campaign-grid {
      display: grid;
      grid-template-columns: minmax(220px, 2fr) repeat(3, minmax(110px, 1fr));
      gap: 10px;
    }
    .campaign label {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .provider-row {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 10px;
    }
    .provider-row label {
      display: inline-flex;
      grid-auto-flow: column;
      align-items: center;
      gap: 5px;
    }
    .provider-row input {
      min-height: auto;
    }
    .market-picker {
      display: grid;
      grid-template-columns: minmax(180px, 240px) 1fr;
      gap: 10px;
      margin-top: 10px;
    }
    .region-list,
    .country-list {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      padding: 8px;
      min-height: 112px;
    }
    .region-list {
      display: grid;
      gap: 5px;
    }
    .country-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 6px 10px;
      align-content: start;
    }
    .check-row {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--ink);
      font-size: 12px;
      line-height: 1.25;
    }
    .campaign .check-row {
      display: inline-flex;
      justify-content: flex-start;
    }
    .check-row input {
      min-height: auto;
      margin: 0;
    }
    .market-title {
      color: var(--muted);
      font-size: 12px;
      margin: 10px 0 5px;
    }
    .selection-count {
      color: var(--muted);
      font-size: 12px;
      margin-left: auto;
    }
    #campaign-summary {
      margin: 10px 0 0;
      white-space: pre-wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 10px 12px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 3px;
    }
    .metric strong {
      font-size: 22px;
      line-height: 1.1;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      background: var(--panel);
    }
    table {
      width: 100%;
      min-width: 1480px;
      border-collapse: collapse;
    }
    th, td {
      border-bottom: 1px solid #e4e9ed;
      padding: 8px 10px;
      text-align: left;
      font-size: 13px;
      vertical-align: top;
    }
    th {
      position: sticky;
      top: 0;
      background: #edf2f1;
      color: #31424d;
      font-size: 12px;
      letter-spacing: 0;
      z-index: 1;
    }
    tr:hover td { background: #faf7ee; }
    a { color: #175e69; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .score {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 24px;
      border-radius: 4px;
      background: #e7f2ed;
      color: var(--good);
      font-weight: 700;
    }
    .score.low { background: #f8eadf; color: var(--warn); }
    .source { color: var(--muted); max-width: 190px; }
    .reason { color: var(--muted); max-width: 280px; }
    .state {
      white-space: nowrap;
      color: var(--muted);
      font-size: 12px;
    }
    .usage {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin: -4px 0 14px;
      color: var(--muted);
      font-size: 12px;
    }
    .empty {
      padding: 36px 12px;
      text-align: left;
      color: var(--muted);
    }
    @media (max-width: 760px) {
      header { grid-template-columns: minmax(0, 1fr); padding: 18px; }
      .toolbar { justify-content: flex-start; }
      main { padding: 14px; }
      .metrics { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .campaign-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
      .campaign-grid label:first-child { grid-column: 1 / -1; }
      .market-picker { grid-template-columns: 1fr; }
      .country-list { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
    }
    @media (max-width: 430px) {
      .country-list { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>玻纤外贸获客工作台</h1>
      <div class="subhead">按 HS 编码、区域市场和国家筛选，自动发现并审核海外客户线索。</div>
    </div>
    <div class="toolbar">
      <select id="status-filter" aria-label="状态筛选">
        <option value="">全部状态</option>
        <option value="Discovered">已发现</option>
        <option value="Enriched">已补全</option>
        <option value="Qualified">已确认</option>
        <option value="Rejected">已拒绝</option>
        <option value="Error">错误</option>
      </select>
      <button type="button" data-review="">全部复核状态</button>
      <button type="button" data-review="high_confidence">高置信 Qualified</button>
      <button type="button" data-review="needs_review">待人工复核</button>
      <button type="button" data-review="suspected_supplier">疑似供应商误判</button>
      <button type="button" data-review="crawl_failed">抓取失败</button>
      <button id="previous-page" type="button" disabled>上一页</button>
      <button id="next-page" type="button">下一页</button>
      <button id="refresh" type="button">刷新</button>
      <button id="requalify" type="button">批量复核旧线索</button>
      <button id="enrich-qualified" type="button">补全合格线索邮箱</button>
      <button id="verify-qualified" type="button">验证已有邮箱</button>
      <button id="export-qualified" type="button">导出 Qualified</button>
      <button id="sync-crm" type="button">同步到 CRM</button>
    </div>
  </header>
  <main>
    <section class="campaign" aria-label="自动搜寻设置">
      <div class="campaign-grid">
        <label>HS 编码
          <select id="campaign-hs">
            <option value="7019">7019 玻璃纤维及其制品（全部）</option>
            <option value="701911">701911 短切原丝，长度不超过 50mm</option>
            <option value="701912">701912 玻璃纤维粗纱 / Rovings</option>
            <option value="701913">701913 其他玻璃纤维纱线、条</option>
            <option value="701914">701914 机械粘结玻璃纤维毡</option>
            <option value="701915">701915 化学粘结玻璃纤维毡</option>
            <option value="701919">701919 其他短切原丝、粗纱、纱线、毡</option>
            <option value="701961">701961 机械粘结织物：粗纱闭合织物</option>
            <option value="701962">701962 机械粘结织物：其他粗纱闭合织物</option>
            <option value="701963">701963 机械粘结织物：纱线平纹闭合织物，未涂层/未层压</option>
            <option value="701964">701964 机械粘结织物：纱线平纹闭合织物，已涂层/层压</option>
            <option value="701965">701965 机械粘结织物：宽度不超过 30cm 的开孔织物</option>
            <option value="701966">701966 机械粘结织物：宽度超过 30cm 的开孔织物</option>
            <option value="701969">701969 其他机械粘结玻璃纤维织物</option>
            <option value="701971">701971 化学粘结织物：薄片 / Voiles</option>
            <option value="701972">701972 化学粘结织物：其他闭合织物</option>
            <option value="701973">701973 化学粘结织物：其他开孔织物</option>
            <option value="701980">701980 玻璃棉及玻璃棉制品</option>
            <option value="701990">701990 其他玻璃纤维及制品</option>
          </select>
        </label>
        <label>年份 <input id="campaign-year" type="number" value="2024"></label>
        <label>产品类型
          <select id="campaign-product">
__PRODUCT_FAMILY_OPTIONS__
          </select>
        </label>
        <label>每国家线索数 <input id="campaign-per-market" type="number" value="10" min="1" max="100"></label>
      </div>
      <div class="market-title">区域市场 <span id="selection-count" class="selection-count">已选择 0 个国家</span></div>
      <div class="market-picker">
        <div id="region-list" class="region-list" aria-label="区域市场"></div>
        <div id="country-list" class="country-list" aria-label="国家选择"></div>
      </div>
      <div class="provider-row">
        <label><input id="campaign-serper" type="checkbox" checked> Serper</label>
        <label><input id="campaign-apollo" type="checkbox"> Apollo</label>
        <label><input id="campaign-hunter" type="checkbox"> Hunter</label>
        <button id="run-campaign" type="button">开始自动搜寻</button>
      </div>
      <pre id="campaign-summary"></pre>
    </section>
    <section class="metrics" aria-label="线索指标">
      <div class="metric"><span>线索总数</span><strong id="metric-total">0</strong></div>
      <div class="metric"><span>合格且有邮箱</span><strong id="metric-email">0</strong></div>
      <div class="metric"><span>已确认</span><strong id="metric-qualified">0</strong></div>
      <div class="metric"><span>错误</span><strong id="metric-errors">0</strong></div>
    </section>
    <section class="usage" aria-label="本次 API 用量">
      <strong>最近运行：</strong>
      <span>Serper <b id="usage-serper">0</b></span>
      <span>Hunter <b id="usage-hunter">0</b></span>
      <span>Apollo <b id="usage-apollo">0</b></span>
      <span id="crm-state">CRM 未连接</span>
    </section>
    <section class="campaign" aria-label="召回质量报告">
      <h2 style="margin:0 0 10px;font-size:16px;">召回质量报告</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>国家</th>
              <th>语言/地区</th>
              <th>产品族</th>
              <th>搜索词</th>
              <th>Serper</th>
              <th>创建</th>
              <th>Qualified</th>
              <th>Rejected</th>
              <th>有效邮箱</th>
              <th>Qualified/Query</th>
            </tr>
          </thead>
          <tbody id="recall-report"><tr><td class="empty" colspan="10">暂无召回报表。</td></tr></tbody>
        </table>
      </div>
    </section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>分数</th>
            <th>公司</th>
            <th>国家/地区</th>
            <th>匹配</th>
            <th>邮箱</th>
            <th>状态</th>
            <th>抓取</th>
            <th>分类</th>
            <th>市场</th>
            <th>邮箱验证</th>
            <th>CRM</th>
            <th>来源</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody id="leads"><tr><td class="empty" colspan="13">正在加载线索...</td></tr></tbody>
      </table>
    </div>
  </main>
  <script>
    const statuses = ['Discovered', 'Enriched', 'Qualified', 'Rejected', 'Error'];
    const productFamilyLabels = __PRODUCT_FAMILY_LABELS__;
    const statusLabels = {
      Discovered: '已发现',
      Enriched: '已补全',
      Qualified: '已确认',
      Rejected: '已拒绝',
      Error: '错误'
    };
    const regionMarkets = {
      '北美': [
        ['USA', '美国'],
        ['Canada', '加拿大'],
        ['Mexico', '墨西哥']
      ],
      '欧洲': [
        ['Germany', '德国'],
        ['France', '法国'],
        ['United Kingdom', '英国'],
        ['Italy', '意大利'],
        ['Spain', '西班牙'],
        ['Netherlands', '荷兰'],
        ['Poland', '波兰']
      ],
      '东南亚': [
        ['Vietnam', '越南'],
        ['Thailand', '泰国'],
        ['Indonesia', '印度尼西亚'],
        ['Malaysia', '马来西亚'],
        ['Philippines', '菲律宾'],
        ['Singapore', '新加坡']
      ],
      '南亚': [
        ['India', '印度'],
        ['Pakistan', '巴基斯坦'],
        ['Bangladesh', '孟加拉国']
      ],
      '中东': [
        ['United Arab Emirates', '阿联酋'],
        ['Saudi Arabia', '沙特阿拉伯'],
        ['Turkey', '土耳其'],
        ['Israel', '以色列']
      ],
      '南美': [
        ['Brazil', '巴西'],
        ['Chile', '智利'],
        ['Argentina', '阿根廷'],
        ['Colombia', '哥伦比亚']
      ],
      '东亚': [
        ['Japan', '日本'],
        ['South Korea', '韩国'],
        ['Taiwan', '中国台湾']
      ],
      '非洲': [
        ['South Africa', '南非'],
        ['Egypt', '埃及'],
        ['Morocco', '摩洛哥'],
        ['Nigeria', '尼日利亚']
      ]
    };
    const selectedRegions = new Set(['北美']);
    const selectedCountries = new Set(regionMarkets['北美'].map(([value]) => value));
    const state = {review: '', offset: 0, limit: 200};
    let currentResultLength = 0;

    function esc(value) {
      return String(value || '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[char]));
    }

    function statusSelect(lead) {
      const options = statuses.map((status) => {
        const selected = status === lead.status ? 'selected' : '';
        return `<option value="${status}" ${selected}>${statusLabels[status] || status}</option>`;
      }).join('');
      return `<select data-lead-id="${lead.id}" aria-label="更新 ${esc(lead.company_name)} 的状态">${options}</select>`;
    }

    function sourceLabel(sourceName) {
      const source = String(sourceName || '');
      if (source.startsWith('Serper:')) return 'Serper';
      return source.length > 28 ? `${source.slice(0, 28)}...` : source;
    }

    function stateLabel(value) {
      const labels = {
        success: '成功', partial: '部分成功', error: '失败',
        downstream_customer: '下游客户', distributor_or_importer: '经销/进口商',
        supplier: '供应商', noise: '噪声', unknown: '待判断',
        passed: '通过', failed: '不通过',
        valid: '有效', invalid: '无效', accept_all: '全收域名',
        not_found: '未找到', synced: '已同步', duplicate: '已存在'
      };
      return labels[value] || value || '—';
    }

    function productFamilyLabel(value) {
      return productFamilyLabels[value] || value || '—';
    }

    function renderMarketPicker() {
      const regionList = document.getElementById('region-list');
      const countryList = document.getElementById('country-list');
      regionList.innerHTML = Object.keys(regionMarkets).map((region) => {
        const checked = selectedRegions.has(region) ? 'checked' : '';
        return `<label class="check-row"><input type="checkbox" data-region="${esc(region)}" ${checked}>${esc(region)}</label>`;
      }).join('');

      const countries = [];
      Object.entries(regionMarkets).forEach(([region, items]) => {
        if (!selectedRegions.has(region)) return;
        items.forEach(([value, label]) => countries.push({region, value, label}));
      });
      countryList.innerHTML = countries.length ? countries.map((country) => {
        const checked = selectedCountries.has(country.value) ? 'checked' : '';
        return `<label class="check-row"><input type="checkbox" data-country="${esc(country.value)}" ${checked}>${esc(country.label)}</label>`;
      }).join('') : '<div class="empty">请先选择区域市场。</div>';

      document.getElementById('selection-count').textContent = `已选择 ${selectedCountries.size} 个国家`;
      regionList.querySelectorAll('input[data-region]').forEach((input) => input.addEventListener('change', updateRegion));
      countryList.querySelectorAll('input[data-country]').forEach((input) => input.addEventListener('change', updateCountry));
    }

    function updateRegion(event) {
      const region = event.target.getAttribute('data-region');
      const countries = regionMarkets[region] || [];
      if (event.target.checked) {
        selectedRegions.add(region);
        countries.forEach(([value]) => selectedCountries.add(value));
      } else {
        selectedRegions.delete(region);
        countries.forEach(([value]) => selectedCountries.delete(value));
      }
      renderMarketPicker();
    }

    function updateCountry(event) {
      const country = event.target.getAttribute('data-country');
      if (event.target.checked) {
        selectedCountries.add(country);
      } else {
        selectedCountries.delete(country);
      }
      document.getElementById('selection-count').textContent = `已选择 ${selectedCountries.size} 个国家`;
    }

    async function updateStatus(event) {
      const select = event.target;
      const leadId = select.getAttribute('data-lead-id');
      if (!leadId) return;
      await fetch(`/api/leads/${leadId}/status`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: select.value})
      });
      await loadLeads();
    }

    async function loadStats() {
      const response = await fetch('/api/stats');
      const stats = await response.json();
      document.getElementById('metric-total').textContent = stats.leads || 0;
      document.getElementById('metric-email').textContent = stats.qualified_with_email || 0;
      document.getElementById('metric-qualified').textContent = (stats.by_status || {}).Qualified || 0;
      document.getElementById('metric-errors').textContent = (stats.by_status || {}).Error || 0;
    }

    async function loadLeads() {
      const filter = document.getElementById('status-filter').value;
      const params = new URLSearchParams({limit: String(state.limit)});
      params.set('offset', String(state.offset));
      if (filter) params.set('status', filter);
      if (state.review) params.set('review', state.review);
      const url = `/api/leads?${params.toString()}`;
      const response = await fetch(url);
      const payload = await response.json();
      const leads = payload.leads || [];
      currentResultLength = leads.length;
      document.getElementById('previous-page').disabled = state.offset === 0;
      document.getElementById('next-page').disabled = currentResultLength !== state.limit;
      const tbody = document.getElementById('leads');
      if (!leads.length) {
        tbody.innerHTML = '<tr><td class="empty" colspan="13">当前视图没有线索。</td></tr>';
        await loadStats();
        return;
      }
      tbody.innerHTML = leads.map((lead) => {
        const scoreClass = Number(lead.match_score || 0) >= 50 ? 'score' : 'score low';
        const website = lead.website || '#';
        const evidence = [
          lead.review_status ? `复核: ${lead.review_status}` : '',
          lead.classification_status ? `分类: ${lead.classification_status}` : '',
          lead.classification_evidence ? `分类依据: ${lead.classification_evidence}` : '',
          lead.score_explanation ? `评分依据: ${lead.score_explanation}` : ''
        ].filter(Boolean).join(' | ');
        return `
          <tr>
            <td><span class="${scoreClass}">${lead.match_score || 0}</span></td>
            <td><a href="${esc(website)}" target="_blank" rel="noreferrer">${esc(lead.company_name)}</a></td>
            <td>${esc(lead.country_region)}</td>
            <td>${esc(lead.product_fit)}</td>
            <td>${esc(lead.email)}</td>
            <td>${statusSelect(lead)}</td>
            <td class="state">${esc(stateLabel(lead.crawl_status))}</td>
            <td class="state">${esc(stateLabel(lead.classification_status))}</td>
            <td class="state">${esc(stateLabel(lead.market_fit_status))}</td>
            <td class="state">${esc(stateLabel(lead.email_verification_status))}</td>
            <td class="state">${esc(stateLabel(lead.crm_sync_status))}</td>
            <td class="source" title="${esc(lead.source_name)}">${esc(sourceLabel(lead.source_name))}</td>
            <td class="reason">${esc(lead.fit_reason)}${evidence ? `<div>${esc(evidence)}</div>` : ''}</td>
          </tr>
        `;
      }).join('');
      tbody.querySelectorAll('select[data-lead-id]').forEach((select) => select.addEventListener('change', updateStatus));
      await loadStats();
    }

    async function loadProviderState() {
      const response = await fetch('/api/provider-state');
      const state = await response.json();
      [
        ['campaign-serper', state.serper],
        ['campaign-apollo', state.apollo],
        ['campaign-hunter', state.hunter]
      ].forEach(([id, enabled]) => {
        const input = document.getElementById(id);
        input.disabled = !enabled;
        if (!enabled) input.checked = false;
      });
      document.getElementById('enrich-qualified').disabled = !state.hunter;
      document.getElementById('verify-qualified').disabled = !state.hunter;
    }

    async function loadUsage() {
      const response = await fetch('/api/usage');
      const payload = await response.json();
      const usage = payload.usage || {};
      document.getElementById('usage-serper').textContent = usage.Serper || 0;
      document.getElementById('usage-hunter').textContent = usage['Hunter.io'] || 0;
      document.getElementById('usage-apollo').textContent = usage['Apollo.io'] || 0;
    }

    async function loadRecallReport(runId = '') {
      const params = new URLSearchParams();
      if (runId) params.set('run_id', String(runId));
      const url = params.size ? `/api/recall-report?${params.toString()}` : '/api/recall-report';
      const response = await fetch(url);
      const payload = await response.json();
      const rows = payload.rows || [];
      const tbody = document.getElementById('recall-report');
      if (!rows.length) {
        tbody.innerHTML = '<tr><td class="empty" colspan="10">暂无召回报表。</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map((row) => `
        <tr>
          <td>${esc(row.country)}</td>
          <td>${esc(row.locale)}</td>
          <td>${esc(productFamilyLabel(row.product_family))}</td>
          <td class="reason">${esc((row.search_terms || []).join(' | '))}</td>
          <td>${row.serper_queries || 0}</td>
          <td>${row.leads_created || 0}</td>
          <td>${row.qualified_count || 0}</td>
          <td>${row.rejected_count || 0}</td>
          <td>${row.valid_email_count || 0}</td>
          <td>${row.qualified_per_query || 0}</td>
        </tr>
      `).join('');
    }

    async function loadCrmState() {
      const response = await fetch('/api/crm-state');
      const payload = await response.json();
      const available = Boolean(payload.available);
      document.getElementById('crm-state').textContent = available ? 'CRM 已连接' : 'CRM 未连接';
      document.getElementById('sync-crm').disabled = !available;
    }

    async function runCampaign() {
      const summary = document.getElementById('campaign-summary');
      const countries = Array.from(selectedCountries);
      if (!countries.length) {
        summary.textContent = '请先选择至少 1 个目标国家。';
        return;
      }
      summary.textContent = '正在自动搜寻... 会消耗已启用 API 的额度，建议先用小批量验证。';
      const response = await fetch('/api/campaign', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          hs_code: document.getElementById('campaign-hs').value,
          year: Number(document.getElementById('campaign-year').value),
          product: document.getElementById('campaign-product').value,
          target_countries: countries,
          per_market_limit: Number(document.getElementById('campaign-per-market').value),
          use_serper: document.getElementById('campaign-serper').checked,
          use_apollo: document.getElementById('campaign-apollo').checked,
          use_hunter: document.getElementById('campaign-hunter').checked
        })
      });
      const payload = await response.json();
      summary.textContent = JSON.stringify(payload.result || payload, null, 2);
      await loadLeads();
      await loadRecallReport(payload.result ? payload.result.run_id : '');
      await loadUsage();
    }

    async function requalifyExistingLeads() {
      const summary = document.getElementById('campaign-summary');
      const button = document.getElementById('requalify');
      button.disabled = true;
      summary.textContent = '正在重新抓取并复核旧线索...';
      try {
        const response = await fetch('/api/requalify', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 100, only_unreviewed: true, min_score: 50})
        });
        const payload = await response.json();
        summary.textContent = JSON.stringify(payload.result || payload, null, 2);
        await loadLeads();
      } finally {
        button.disabled = false;
      }
    }

    async function enrichQualifiedEmails() {
      const summary = document.getElementById('campaign-summary');
      const button = document.getElementById('enrich-qualified');
      button.disabled = true;
      summary.textContent = '正在为已确认线索查询并验证邮箱...';
      try {
        const response = await fetch('/api/enrich-qualified', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 5})
        });
        const payload = await response.json();
        summary.textContent = JSON.stringify(payload.result || payload, null, 2);
        await loadLeads();
      } finally {
        await loadProviderState();
      }
    }

    async function verifyQualifiedEmails() {
      const summary = document.getElementById('campaign-summary');
      const button = document.getElementById('verify-qualified');
      button.disabled = true;
      summary.textContent = '正在验证 Qualified 线索已有邮箱...';
      try {
        const response = await fetch('/api/verify-qualified-emails', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 10})
        });
        const payload = await response.json();
        summary.textContent = JSON.stringify(payload.result || payload, null, 2);
        await loadLeads();
      } finally {
        await loadProviderState();
      }
    }

    async function syncCrm() {
      const summary = document.getElementById('campaign-summary');
      const button = document.getElementById('sync-crm');
      button.disabled = true;
      summary.textContent = '正在将已验证的 Qualified 线索同步到 CRM...';
      try {
        const response = await fetch('/api/sync-crm', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 50})
        });
        const payload = await response.json();
        summary.textContent = JSON.stringify(payload.result || payload, null, 2);
        await loadLeads();
      } finally {
        await loadCrmState();
      }
    }

    document.getElementById('refresh').addEventListener('click', loadLeads);
    document.getElementById('status-filter').addEventListener('change', () => {
      state.offset = 0;
      loadLeads();
    });
    document.querySelectorAll('[data-review]').forEach((button) => button.addEventListener('click', () => {
      state.review = button.getAttribute('data-review') || '';
      state.offset = 0;
      loadLeads();
    }));
    document.getElementById('previous-page').addEventListener('click', () => {
      state.offset = Math.max(0, state.offset - state.limit);
      loadLeads();
    });
    document.getElementById('next-page').addEventListener('click', () => {
      if (currentResultLength !== state.limit) return;
      state.offset += state.limit;
      loadLeads();
    });
    document.getElementById('run-campaign').addEventListener('click', runCampaign);
    document.getElementById('requalify').addEventListener('click', requalifyExistingLeads);
    document.getElementById('enrich-qualified').addEventListener('click', enrichQualifiedEmails);
    document.getElementById('verify-qualified').addEventListener('click', verifyQualifiedEmails);
    document.getElementById('export-qualified').addEventListener('click', () => {
      window.location.href = '/api/export-qualified';
    });
    document.getElementById('sync-crm').addEventListener('click', syncCrm);
    renderMarketPicker();
    loadProviderState();
    loadUsage();
    loadRecallReport();
    loadCrmState();
    loadLeads();
  </script>
</body>
</html>
"""
INDEX_HTML = INDEX_HTML.replace("__PRODUCT_FAMILY_OPTIONS__", PRODUCT_FAMILY_OPTIONS_HTML).replace(
    "__PRODUCT_FAMILY_LABELS__",
    json.dumps(WEB_PRODUCT_FAMILY_LABELS, ensure_ascii=False),
)


@dataclass(frozen=True)
class LocalLeadApp:
    db_path: Path

    def handle(self, method: str, path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(path)
        if method == "GET" and parsed.path == "/":
            return (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                INDEX_HTML.encode("utf-8"),
            )

        if method == "GET" and parsed.path == "/api/leads":
            query = parse_qs(parsed.query, keep_blank_values=True)
            status = query.get("status", [None])[0]
            review = query.get("review", [None])[0]
            limit_text = query.get("limit", ["100"])[0]
            limit = max(1, min(int(limit_text), 500))
            offset_text = query.get("offset", ["0"])[0]
            try:
                offset = int(offset_text)
            except (TypeError, ValueError):
                return self.json_response({"error": "invalid offset"}, status=400)
            if offset < 0:
                return self.json_response({"error": "invalid offset"}, status=400)
            if review and review not in SUPPORTED_REVIEWS:
                return self.json_response({"error": "invalid review"}, status=400)
            db = connect(self.db_path)
            try:
                if review:
                    leads = []
                    source_offset = 0
                    matching_rows = 0
                    while len(leads) < limit:
                        chunk = list_leads(db, status=status, limit=500, offset=source_offset)
                        decorated = [_decorate_lead_for_display(lead) for lead in chunk]
                        for lead in decorated:
                            if lead["review_status"] == review:
                                if matching_rows < offset:
                                    matching_rows += 1
                                    continue
                                leads.append(lead)
                                matching_rows += 1
                                if len(leads) >= limit:
                                    break
                        if len(leads) >= limit or len(chunk) < 500:
                            break
                        source_offset += 500
                else:
                    leads = list_leads(db, status=status, limit=limit, offset=offset)
                    leads = [_decorate_lead_for_display(lead) for lead in leads]
            finally:
                db.close()
            return self.json_response({"leads": leads, "offset": offset, "limit": limit})

        if method == "GET" and parsed.path == "/api/stats":
            db = connect(self.db_path)
            try:
                payload = stats(db)
            finally:
                db.close()
            return self.json_response(payload)

        if method == "GET" and parsed.path == "/api/usage":
            db = connect(self.db_path)
            try:
                payload = latest_provider_usage(db)
            finally:
                db.close()
            return self.json_response(payload)

        if method == "GET" and parsed.path == "/api/recall-report":
            query = parse_qs(parsed.query, keep_blank_values=True)
            run_id_text = query.get("run_id", [""])[0]
            try:
                run_id = int(run_id_text) if run_id_text else None
            except (TypeError, ValueError):
                return self.json_response({"error": "invalid run_id"}, status=400)
            db = connect(self.db_path)
            try:
                payload = recall_report(db, run_id)
            finally:
                db.close()
            return self.json_response(payload)

        if method == "GET" and parsed.path == "/api/export-qualified":
            db = connect(self.db_path)
            try:
                leads = list_leads(db, status="Qualified")
            finally:
                db.close()
            return (
                200,
                {
                    "Content-Type": "text/csv; charset=utf-8",
                    "Content-Disposition": 'attachment; filename="qualified_leads.csv"',
                },
                export_csv_bytes(leads),
            )

        if method == "GET" and parsed.path == "/api/provider-state":
            cfg = settings()
            return self.json_response(
                {
                    "serper": bool(cfg.serper_api_key),
                    "apollo": bool(cfg.apollo_api_key),
                    "hunter": bool(cfg.hunter_api_key),
                }
            )

        if method == "GET" and parsed.path == "/api/crm-state":
            cfg = settings()
            try:
                payload = crm_status(cfg.crm_url, timeout=min(cfg.timeout_seconds, 3.0))
            except Exception as error:
                payload = {"available": False, "error": sanitize_error(error)}
            return self.json_response(payload)

        if method == "POST" and parsed.path == "/api/campaign":
            cfg = settings()
            payload = json.loads(body.decode("utf-8") or "{}")
            use_serper = bool(payload.get("use_serper", True)) and bool(cfg.serper_api_key)
            use_apollo = bool(payload.get("use_apollo", False)) and bool(cfg.apollo_api_key)
            use_hunter = bool(payload.get("use_hunter", False)) and bool(cfg.hunter_api_key)
            raw_countries = payload.get("target_countries", [])
            if not isinstance(raw_countries, list):
                raw_countries = []
            countries = tuple(
                str(country).strip()
                for country in raw_countries
                if str(country).strip()
            )[:50]
            options = CampaignOptions(
                hs_code=str(payload.get("hs_code") or "7019"),
                year=int(payload.get("year") or 2024),
                product=str(payload.get("product") or "both"),
                market_limit=len(countries) if countries else max(1, min(int(payload.get("market_limit") or 5), 20)),
                per_market_limit=max(1, min(int(payload.get("per_market_limit") or 20), 100)),
                target_countries=countries,
                min_score=int(payload.get("min_score") or 50),
                use_serper=use_serper,
                use_apollo=use_apollo,
                use_hunter=use_hunter,
                timeout_seconds=cfg.timeout_seconds,
            )
            db = connect(self.db_path)
            try:
                result = run_campaign(
                    db,
                    options,
                    serper_client=SerperClient(cfg.serper_api_key, timeout=cfg.timeout_seconds) if use_serper else None,
                    apollo_client=ApolloClient(cfg.apollo_api_key, timeout=cfg.timeout_seconds) if use_apollo else None,
                    hunter_client=HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds) if use_hunter else None,
                )
            finally:
                db.close()
            return self.json_response({"result": result})

        if method == "POST" and parsed.path == "/api/requalify":
            cfg = settings()
            payload = json.loads(body.decode("utf-8") or "{}")
            options = RequalifyOptions(
                limit=max(1, min(int(payload.get("limit") or 100), 500)),
                min_score=max(0, min(int(payload.get("min_score") or 50), 100)),
                only_unreviewed=bool(payload.get("only_unreviewed", True)),
                timeout_seconds=cfg.timeout_seconds,
            )
            db = connect(self.db_path)
            try:
                result = requalify_leads(db, options)
            finally:
                db.close()
            return self.json_response({"result": result})

        if method == "POST" and parsed.path == "/api/enrich-qualified":
            cfg = settings()
            if not cfg.hunter_api_key:
                return self.json_response({"error": "HUNTER_API_KEY missing"}, status=400)
            payload = json.loads(body.decode("utf-8") or "{}")
            limit = max(1, min(int(payload.get("limit") or 5), 50))
            db = connect(self.db_path)
            try:
                result = enrich_qualified_emails(
                    db,
                    HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds),
                    limit=limit,
                )
            finally:
                db.close()
            return self.json_response({"result": result})

        if method == "POST" and parsed.path == "/api/verify-qualified-emails":
            cfg = settings()
            if not cfg.hunter_api_key:
                return self.json_response({"error": "HUNTER_API_KEY missing"}, status=400)
            payload = json.loads(body.decode("utf-8") or "{}")
            limit = max(1, min(int(payload.get("limit") or 10), 50))
            db = connect(self.db_path)
            try:
                result = verify_existing_qualified_emails(
                    db,
                    HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds),
                    limit=limit,
                )
            finally:
                db.close()
            return self.json_response({"result": result})

        if method == "POST" and parsed.path == "/api/sync-crm":
            cfg = settings()
            payload = json.loads(body.decode("utf-8") or "{}")
            limit = max(1, min(int(payload.get("limit") or 50), 200))
            try:
                crm_status(cfg.crm_url, timeout=min(cfg.timeout_seconds, 3.0))
            except Exception as error:
                return self.json_response(
                    {"error": sanitize_error(error)},
                    status=503,
                )
            db = connect(self.db_path)
            try:
                result = sync_verified_qualified(
                    db,
                    cfg.crm_url,
                    limit=limit,
                    timeout=min(cfg.timeout_seconds, 8.0),
                )
            finally:
                db.close()
            return self.json_response({"result": result})

        match = re.fullmatch(r"/api/leads/(\d+)/status", parsed.path)
        if method == "POST" and match:
            lead_id = int(match.group(1))
            payload = json.loads(body.decode("utf-8") or "{}")
            next_status = str(payload.get("status", "")).strip()
            if next_status not in ALLOWED_STATUSES:
                return self.json_response({"error": "invalid status"}, status=400)
            db = connect(self.db_path)
            try:
                lead = update_lead(
                    db,
                    lead_id,
                    {"status": next_status, "review_status": ""},
                )
            finally:
                db.close()
            return self.json_response({"lead": lead})

        return self.json_response({"error": "not found"}, status=404)

    def json_response(self, payload: dict, status: int = 200) -> tuple[int, dict[str, str], bytes]:
        return (
            status,
            {"Content-Type": "application/json; charset=utf-8"},
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )


def _decorate_lead_for_display(lead: dict) -> dict:
    evidence = parse_score_evidence(lead.get("score_evidence", ""))
    display = dict(lead)
    display["score_explanation"] = score_reason_text(evidence)
    display["review_status"] = review_status_for_lead(display)
    return display


def make_app(db_path: str | Path) -> LocalLeadApp:
    return LocalLeadApp(Path(db_path))


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    app = make_app(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b""
            try:
                status, headers, response_body = app.handle(self.command, self.path, body)
            except Exception as error:
                status, headers, response_body = app.json_response(
                    {"error": sanitize_error(error)},
                    status=500,
                )
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Lead Finder Workbench: http://{host}:{port}")
    server.serve_forever()
