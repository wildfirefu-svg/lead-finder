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
from .crm import crm_status, pull_crm_feedback, sync_verified_qualified
from .db import (
    connect,
    create_run_log,
    daily_run_usage,
    finish_run_log,
    list_provider_tasks,
    list_provider_tasks_by_ids,
    latest_provider_usage,
    list_leads,
    mark_provider_task_ids_for_retry,
    record_run_usage,
    stats,
    update_lead,
)
from .evidence import parse_score_evidence, review_status_for_lead, score_reason_text
from .exporter import export_csv_bytes
from .feedback import crm_feedback_report
from .hunter import HunterClient
from .query_catalog import PRODUCT_FAMILY_LABELS
from .recall import recall_report
from .requalify import RequalifyOptions, requalify_leads
from .security import sanitize_error
from .serper import SerperClient
from .stability import BudgetManager, budget_limits_from_settings, budget_snapshot


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
      grid-template-columns: minmax(0, 1fr);
      gap: 14px;
      align-items: stretch;
      padding: 22px 28px 18px;
      background: var(--rail);
      color: #f8faf2;
      border-bottom: 4px solid var(--accent-2);
    }
    .header-main {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
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
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 6px;
      background: rgba(12, 21, 31, 0.28);
    }
    .toolbar-row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .toolbar-group {
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
      padding: 6px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.06);
    }
    .toolbar-group.filters {
      flex: 1 1 100%;
    }
    .toolbar-group.actions {
      flex: 1 1 auto;
    }
    .toolbar-group.crm {
      flex: 0 1 auto;
    }
    .toolbar-label {
      color: #c9d4dc;
      font-size: 11px;
      white-space: nowrap;
      padding: 0 3px;
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
    .toolbar button,
    .toolbar select {
      min-height: 30px;
      padding: 4px 8px;
      font-size: 12px;
    }
    .toolbar select {
      min-width: 110px;
      background: #f7fafb;
    }
    .toolbar button {
      white-space: nowrap;
    }
    .action-button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      line-height: 1;
    }
    .action-button::before {
      content: '';
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: #b7c4cc;
      box-shadow: 0 0 0 1px rgba(90, 110, 123, 0.22);
      flex: 0 0 auto;
    }
    .action-button[data-run-state="working"]::before {
      background: #cf9a2a;
      box-shadow: 0 0 0 3px rgba(207, 154, 42, 0.18);
    }
    .action-button[data-run-state="success"]::before {
      background: #2d8f5f;
      box-shadow: 0 0 0 3px rgba(45, 143, 95, 0.16);
    }
    .action-button[data-run-state="error"]::before {
      background: #b05c2c;
      box-shadow: 0 0 0 3px rgba(176, 92, 44, 0.16);
    }
    .toolbar button[aria-pressed="true"] {
      background: var(--accent);
      color: #f8fbfa;
      border-color: rgba(255, 255, 255, 0.12);
    }
    .toolbar button[aria-pressed="true"]:hover {
      background: #23847d;
      border-color: rgba(255, 255, 255, 0.16);
    }
    .toolbar button:disabled {
      opacity: 0.56;
      cursor: default;
      background: #dce4e9;
      border-color: #b8c4cc;
    }
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
      gap: 10px;
      margin-top: 10px;
    }
    .provider-options {
      display: inline-flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      min-height: 30px;
      padding: 4px 8px;
      border: 1px solid #dbe3e8;
      border-radius: 6px;
      background: #f8fafb;
    }
    .provider-row label {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 30px;
      padding: 0 1px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .provider-row input {
      min-height: auto;
      margin: 0;
    }
    .provider-row button {
      min-height: 30px;
      padding: 4px 8px;
      font-size: 12px;
      white-space: nowrap;
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
    .summary-card {
      margin: 10px 0 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f9fbfc;
    }
    .summary-card--idle {
      background: #f9fbfc;
    }
    .summary-card--working {
      background: #f4f8fb;
      border-color: #c8d8e4;
    }
    .summary-card--success {
      background: #f3f8f5;
      border-color: #c8dbcf;
    }
    .summary-card--warn {
      background: #fbf7ef;
      border-color: #e2d2b0;
    }
    .summary-eyebrow {
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 4px;
    }
    .summary-title {
      font-size: 15px;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 8px;
    }
    .summary-body {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .summary-body p {
      margin: 0;
    }
    .summary-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .summary-metric {
      padding: 8px 9px;
      border: 1px solid #dbe3e8;
      border-radius: 6px;
      background: #fff;
    }
    .summary-metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 3px;
    }
    .summary-metric strong {
      font-size: 18px;
      line-height: 1;
      color: var(--ink);
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
    .panel-controls {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .panel-controls select,
    .panel-controls button {
      min-height: 30px;
      padding: 4px 8px;
      font-size: 12px;
    }
    .panel-status {
      color: var(--muted);
      font-size: 12px;
      margin-left: auto;
    }
    .task-key {
      max-width: 240px;
      color: var(--muted);
      word-break: break-all;
      font-size: 12px;
    }
    .task-message {
      max-width: 320px;
      color: var(--muted);
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .task-checkbox {
      width: 32px;
    }
    .empty {
      padding: 36px 12px;
      text-align: left;
      color: var(--muted);
    }
    @media (max-width: 760px) {
      header { grid-template-columns: minmax(0, 1fr); padding: 18px; }
      .header-main { align-items: start; }
      .toolbar { padding: 10px; }
      .toolbar-row { flex-direction: column; align-items: stretch; }
      .toolbar-group {
        width: 100%;
        align-items: stretch;
      }
      .toolbar-label {
        width: 100%;
        padding-bottom: 2px;
      }
      main { padding: 14px; }
      .metrics { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .campaign-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
      .campaign-grid label:first-child { grid-column: 1 / -1; }
      .market-picker { grid-template-columns: 1fr; }
      .country-list { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .provider-row { align-items: stretch; }
      .provider-options {
        width: 100%;
        justify-content: flex-start;
      }
    }
    @media (max-width: 430px) {
      .country-list { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="header-main">
      <h1>玻纤外贸获客工作台</h1>
      <div class="subhead">按 HS 编码、区域市场和国家筛选，自动发现并审核海外客户线索。</div>
    </div>
    <div class="toolbar">
      <div class="toolbar-row">
        <div class="toolbar-group filters">
          <span class="toolbar-label">筛选</span>
          <select id="status-filter" aria-label="状态筛选">
            <option value="">全部状态</option>
            <option value="Discovered">已发现</option>
            <option value="Enriched">已补全</option>
            <option value="Qualified">已确认</option>
            <option value="Rejected">已拒绝</option>
            <option value="Error">错误</option>
          </select>
          <button type="button" data-review="" aria-pressed="true">全部复核</button>
          <button type="button" data-review="high_confidence" aria-pressed="false">高置信</button>
          <button type="button" data-review="needs_review" aria-pressed="false">待复核</button>
          <button type="button" data-review="suspected_supplier" aria-pressed="false">供应商误判</button>
          <button type="button" data-review="crawl_failed" aria-pressed="false">抓取失败</button>
        </div>
      </div>
      <div class="toolbar-row">
        <div class="toolbar-group">
          <span class="toolbar-label">浏览</span>
          <button id="previous-page" type="button" disabled>上一页</button>
          <button id="next-page" type="button">下一页</button>
          <button id="refresh" type="button">刷新</button>
        </div>
        <div class="toolbar-group actions">
          <span class="toolbar-label">批量处理</span>
          <button id="requalify" class="action-button" type="button">批量复核</button>
          <button id="enrich-qualified" class="action-button" type="button">补全邮箱</button>
          <button id="verify-qualified" class="action-button" type="button">验证邮箱</button>
          <button id="export-qualified" type="button">导出 Qualified</button>
        </div>
        <div class="toolbar-group crm">
          <span class="toolbar-label">CRM</span>
          <button id="sync-crm" class="action-button" type="button">同步 CRM</button>
          <button id="pull-crm-feedback" class="action-button" type="button">拉取反馈</button>
        </div>
      </div>
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
        <div class="provider-options">
          <label><input id="campaign-serper" type="checkbox" checked> Serper</label>
          <label><input id="campaign-apollo" type="checkbox"> Apollo</label>
          <label><input id="campaign-hunter" type="checkbox"> Hunter</label>
        </div>
        <button id="run-campaign" class="action-button" type="button">开始自动搜寻</button>
      </div>
      <section id="campaign-summary" class="summary-card summary-card--idle" aria-live="polite"></section>
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
    <section class="campaign" aria-label="失败任务与重跑标记">
      <h2 style="margin:0 0 10px;font-size:16px;">失败任务 / 标记重跑</h2>
      <div class="panel-controls">
        <select id="provider-task-provider" aria-label="任务来源">
          <option value="">全部来源</option>
          <option value="Serper">Serper</option>
          <option value="Apollo.io">Apollo</option>
          <option value="Hunter.io">Hunter</option>
        </select>
        <select id="provider-task-scope" aria-label="任务范围">
          <option value="failed">仅看失败/中断</option>
          <option value="marked">仅看已标记重跑</option>
          <option value="all">全部任务</option>
        </select>
        <button id="provider-task-refresh" type="button">查看失败任务</button>
        <button id="provider-task-mark-retry" class="action-button" type="button">标记重跑</button>
        <span id="provider-task-status" class="panel-status">正在加载失败任务...</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="task-checkbox"><input id="provider-task-select-all" type="checkbox" aria-label="全选失败任务"></th>
              <th>来源</th>
              <th>任务</th>
              <th>线索</th>
              <th>状态</th>
              <th>重跑标记</th>
              <th>次数</th>
              <th>任务键</th>
              <th>最后结果</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody id="provider-task-report"><tr><td class="empty" colspan="10">正在加载失败任务...</td></tr></tbody>
        </table>
      </div>
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
    <section class="campaign" aria-label="CRM反馈总结">
      <h2 style="margin:0 0 10px;font-size:16px;">CRM反馈总结</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>国家</th>
              <th>产品族</th>
              <th>分类规则</th>
              <th>搜索词</th>
              <th>有效客户</th>
              <th>非买家</th>
              <th>错市场</th>
              <th>重复</th>
              <th>无回复</th>
              <th>勿联系</th>
              <th>建议</th>
            </tr>
          </thead>
          <tbody id="crm-feedback-report"><tr><td class="empty" colspan="11">暂无 CRM 反馈。</td></tr></tbody>
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
            <th>CRM反馈</th>
            <th>来源</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody id="leads"><tr><td class="empty" colspan="14">正在加载线索...</td></tr></tbody>
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
    const selectedProviderTaskIds = new Set();
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
        running: '中断/未完成', completed: '已完成',
        budget_stop: '额度停止', deduped: '去重跳过', retry_required: '待标记重跑',
        downstream_customer: '下游客户', distributor_or_importer: '经销/进口商',
        supplier: '供应商', noise: '噪声', unknown: '待判断',
        passed: '通过', failed: '不通过',
        valid: '有效', invalid: '无效', accept_all: '全收域名',
        not_found: '未找到', synced: '已同步', duplicate: '已存在',
        valid_customer: '有效客户', not_buyer: '非买家', wrong_market: '错市场',
        no_response: '无回复', do_not_contact: '勿联系',
        prioritize_follow_up: '优先跟进', needs_manual_confirmation: '待人工确认',
        Replied: '已回复', Sent: '已发送', Drafted: '已生成草稿',
        New: '新线索', Unsubscribed: '已退订'
      };
      return labels[value] || value || '—';
    }

    function syncToolbarState() {
      document.querySelectorAll('[data-review]').forEach((button) => {
        const review = button.getAttribute('data-review') || '';
        button.setAttribute('aria-pressed', review === state.review ? 'true' : 'false');
      });
    }

    const actionButtonIds = [
      'run-campaign',
      'requalify',
      'enrich-qualified',
      'verify-qualified',
      'sync-crm',
      'pull-crm-feedback',
      'provider-task-mark-retry',
    ];

    function setActionButtonState(buttonId, runState) {
      const button = document.getElementById(buttonId);
      if (!button) return;
      if (!runState || runState === 'idle') {
        button.removeAttribute('data-run-state');
        return;
      }
      button.setAttribute('data-run-state', runState);
    }

    function clearActionButtonStates(activeButtonId = '') {
      actionButtonIds.forEach((buttonId) => {
        if (buttonId === activeButtonId) return;
        setActionButtonState(buttonId, 'idle');
      });
    }

    function renderActionSummary(buttonId, summary) {
      renderSummaryCard(summary);
      if (summary && summary.tone === 'warn') {
        setActionButtonState(buttonId, 'error');
        return;
      }
      setActionButtonState(buttonId, 'success');
    }

    function formatActionError(eyebrow, error) {
      const detail = error && error.message ? error.message : '请稍后重试，或检查接口与网络状态。';
      return {
        tone: 'warn',
        eyebrow,
        title: '执行失败',
        lines: ['这一步没有跑完。', detail],
      };
    }

    function formatProviderTaskRetrySummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '标记重跑',
          title: '已完成',
          lines: ['失败任务已更新。'],
        };
      }
      const marked = Number(result.marked || 0);
      const eligible = Number(result.eligible || 0);
      const alreadyMarked = Number(result.already_marked || 0);
      const notEligible = Number(result.not_eligible || 0);
      const selected = Number(result.selected || 0);
      if (!selected) {
        return {
          tone: 'warn',
          eyebrow: '标记重跑',
          title: '没有选中任务',
          lines: ['请先勾选要重跑的失败任务。'],
        };
      }
      if (!marked) {
        return {
          tone: 'warn',
          eyebrow: '标记重跑',
          title: '没有可标记任务',
          lines: [
            alreadyMarked > 0
              ? `选中的任务里，有 ${alreadyMarked} 个本来就已经标记过重跑。`
              : '选中的任务里，没有处于失败或中断状态的项目。',
            notEligible > 0 ? `${notEligible} 个任务当前不需要重跑标记。` : '',
          ].filter(Boolean),
          metrics: [
            {label: '选中', value: selected},
            {label: '可标记', value: eligible},
            ...(alreadyMarked ? [{label: '已标记', value: alreadyMarked}] : []),
            ...(notEligible ? [{label: '不可标记', value: notEligible}] : []),
          ],
        };
      }
      return {
        tone: 'success',
        eyebrow: '标记重跑',
        title: `已标记 ${marked} 个任务`,
        lines: [
          '这些失败或中断任务下次运行时允许重新调用付费 API。',
          marked < selected ? `本次共选中 ${selected} 个，其中 ${alreadyMarked} 个原本已标记，${notEligible} 个当前不需要重跑标记。`
            : '本次选中的任务都已完成重跑标记。',
        ],
        metrics: [
          {label: '选中', value: selected},
          {label: '已标记', value: marked},
          {label: '可重跑', value: eligible},
          ...(alreadyMarked ? [{label: '原已标记', value: alreadyMarked}] : []),
          ...(notEligible ? [{label: '不可标记', value: notEligible}] : []),
        ],
      };
    }

    function renderSummaryCard(summary) {
      const panel = document.getElementById('campaign-summary');
      const tone = summary && summary.tone ? summary.tone : 'idle';
      const eyebrow = esc(summary && summary.eyebrow ? summary.eyebrow : '运行结果');
      const title = esc(summary && summary.title ? summary.title : '等待执行');
      const lines = Array.isArray(summary && summary.lines) ? summary.lines : [];
      const metrics = Array.isArray(summary && summary.metrics) ? summary.metrics : [];
      const bodyHtml = lines.length
        ? lines.map((line) => `<p>${esc(line)}</p>`).join('')
        : '<p>执行自动搜寻、补全邮箱、验证邮箱、同步 CRM 或拉取反馈后，这里会显示摘要。</p>';
      const metricsHtml = metrics.length
        ? `<div class="summary-metrics">${metrics.map((item) => `
            <div class="summary-metric">
              <span>${esc(item.label)}</span>
              <strong>${esc(item.value)}</strong>
            </div>
          `).join('')}</div>`
        : '';
      panel.className = `summary-card summary-card--${tone}`;
      panel.innerHTML = `
        <div class="summary-eyebrow">${eyebrow}</div>
        <div class="summary-title">${title}</div>
        <div class="summary-body">${bodyHtml}</div>
        ${metricsHtml}
      `;
    }

    function formatRequalifySummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '批量复核',
          title: '已完成',
          lines: ['批量复核已完成。'],
        };
      }
      const reviewed = Number(result.reviewed || 0);
      const qualified = Number(result.qualified || 0);
      const rejected = Number(result.rejected || 0);
      const needsReview = Number(result.needs_review || 0);
      const errors = Number(result.errors || 0);
      if (!reviewed && !errors) {
        return {
          tone: 'success',
          eyebrow: '批量复核',
          title: '没有可复核线索',
          lines: ['批量复核已完成，本次没有可复核的旧线索。'],
          metrics: [
            {label: '复核', value: reviewed},
            {label: '错误', value: errors},
          ],
        };
      }
      return {
        tone: errors > 0 ? 'warn' : 'success',
        eyebrow: '批量复核',
        title: `已完成，共复核 ${reviewed} 条`,
        lines: [
          `已确认 ${qualified} 条，已拒绝 ${rejected} 条，待人工复核 ${needsReview} 条。`,
          errors > 0 ? `处理错误 ${errors} 条。` : '没有处理错误。',
        ],
        metrics: [
          {label: '复核', value: reviewed},
          {label: '确认', value: qualified},
          {label: '拒绝', value: rejected},
          {label: '待复核', value: needsReview},
        ],
      };
    }

    function formatSyncCrmSummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '同步 CRM',
          title: '已完成',
          lines: ['同步 CRM 已完成。'],
        };
      }
      const attempted = Number(result.attempted || 0);
      const synced = Number(result.synced || 0);
      const duplicates = Number(result.duplicates || 0);
      const skippedUnverified = Number(result.skipped_unverified || 0);
      const errors = Number(result.errors || 0);
      if (!attempted && !duplicates && !skippedUnverified && !errors) {
        return {
          tone: 'success',
          eyebrow: '同步 CRM',
          title: '没有可同步线索',
          lines: ['同步 CRM 已完成，本次没有可同步的线索。'],
          metrics: [
            {label: '尝试', value: attempted},
            {label: '跳过未验证', value: skippedUnverified},
          ],
        };
      }
      return {
        tone: errors > 0 ? 'warn' : 'success',
        eyebrow: '同步 CRM',
        title: `已完成，尝试 ${attempted} 条`,
        lines: [
          `成功同步 ${synced} 条，CRM 已存在 ${duplicates} 条，未验证跳过 ${skippedUnverified} 条。`,
          errors > 0 ? `同步失败 ${errors} 条。` : '没有同步错误。',
        ],
        metrics: [
          {label: '尝试', value: attempted},
          {label: '同步成功', value: synced},
          {label: '已存在', value: duplicates},
          {label: '未验证跳过', value: skippedUnverified},
        ],
      };
    }

    function formatCampaignSummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '自动搜寻',
          title: '已完成',
          lines: ['自动搜寻已完成。'],
        };
      }
      const runId = Number(result.run_id || 0);
      const created = Number(result.created || 0);
      const skipped = Number(result.skipped || 0);
      const errors = Number(result.errors || 0);
      const qualityAfter = result.quality_after || {};
      const total = Number(qualityAfter.total || 0);
      const withEmail = Number(qualityAfter.with_email || 0);
      const highQuality = Number(qualityAfter.high_quality || 0);
      const highScore = Number(qualityAfter.high_score || 0);
      const dedupedTasks = Number(result.deduped_tasks || 0);
      const retryRequiredTasks = Number(result.retry_required_tasks || 0);
      const budgetStops = Array.isArray(result.budget_stops) ? result.budget_stops : [];
      return {
        tone: errors > 0 || budgetStops.length > 0 || retryRequiredTasks > 0 ? 'warn' : 'success',
        eyebrow: '自动搜寻',
        title: `已完成${runId ? `，任务 #${runId}` : ''}`,
        lines: [
          `本次新增 ${created} 条线索，跳过 ${skipped} 条。`,
          `当前线索池共 ${total} 条，其中高分 ${highScore} 条、有邮箱 ${withEmail} 条、高质量 ${highQuality} 条。`,
          errors > 0 ? `过程中出现 ${errors} 条错误。` : '过程中没有错误。',
          dedupedTasks > 0 ? `已跳过 ${dedupedTasks} 个已完成的付费任务，避免重复扣费。` : '',
          retryRequiredTasks > 0 ? `${retryRequiredTasks} 个失败或中断任务需要先标记重跑，当前不会再次调用付费 API。` : '',
          budgetStops.length ? `额度保护已触发：${budgetStops.map((item) => item.message || '').filter(Boolean).join('；')}` : '',
        ].filter(Boolean),
        metrics: [
          {label: '新增', value: created},
          {label: '跳过', value: skipped},
          {label: '高分', value: highScore},
          {label: '有邮箱', value: withEmail},
          ...(dedupedTasks ? [{label: '去重跳过', value: dedupedTasks}] : []),
          ...(retryRequiredTasks ? [{label: '待重跑', value: retryRequiredTasks}] : []),
          ...(budgetStops.length ? [{label: '额度触发', value: budgetStops.length}] : []),
        ],
      };
    }

    function formatEnrichSummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '补全邮箱',
          title: '已完成',
          lines: ['补全邮箱已完成。'],
        };
      }
      const attempted = Number(result.attempted || 0);
      const emailsFound = Number(result.emails_found || 0);
      const verified = Number(result.verified || 0);
      const noEmail = Number(result.no_email || 0);
      const errors = Number(result.errors || 0);
      const dedupedTasks = Number(result.deduped_tasks || 0);
      const retryRequiredTasks = Number(result.retry_required_tasks || 0);
      const budgetStops = Array.isArray(result.budget_stops) ? result.budget_stops : [];
      if (!attempted && !errors) {
        return {
          tone: budgetStops.length || retryRequiredTasks ? 'warn' : 'success',
          eyebrow: '补全邮箱',
          title: budgetStops.length ? '额度已触发' : retryRequiredTasks ? '存在待重跑任务' : '没有符合条件线索',
          lines: [
            '补全邮箱已完成，本次没有符合条件的 Qualified 线索。',
            dedupedTasks > 0 ? `已跳过 ${dedupedTasks} 个已完成任务。` : '',
            retryRequiredTasks > 0 ? `${retryRequiredTasks} 个失败任务需要先标记重跑。` : '',
            budgetStops.length ? budgetStops.map((item) => item.message || '').filter(Boolean).join('；') : '',
          ].filter(Boolean),
          metrics: [
            {label: '处理', value: attempted},
            {label: '错误', value: errors},
            ...(dedupedTasks ? [{label: '去重跳过', value: dedupedTasks}] : []),
            ...(retryRequiredTasks ? [{label: '待重跑', value: retryRequiredTasks}] : []),
          ],
        };
      }
      return {
        tone: errors > 0 || budgetStops.length || retryRequiredTasks ? 'warn' : 'success',
        eyebrow: '补全邮箱',
        title: `已完成，共处理 ${attempted} 条`,
        lines: [
          `找到邮箱 ${emailsFound} 条，其中验证通过 ${verified} 条，未找到邮箱 ${noEmail} 条。`,
          errors > 0 ? `处理错误 ${errors} 条。` : '没有处理错误。',
          dedupedTasks > 0 ? `已跳过 ${dedupedTasks} 个已完成任务，避免重复扣费。` : '',
          retryRequiredTasks > 0 ? `${retryRequiredTasks} 个失败任务需要先标记重跑。` : '',
          budgetStops.length ? `额度保护已触发：${budgetStops.map((item) => item.message || '').filter(Boolean).join('；')}` : '',
        ].filter(Boolean),
        metrics: [
          {label: '处理', value: attempted},
          {label: '找到邮箱', value: emailsFound},
          {label: '验证通过', value: verified},
          {label: '未找到', value: noEmail},
          ...(dedupedTasks ? [{label: '去重跳过', value: dedupedTasks}] : []),
          ...(retryRequiredTasks ? [{label: '待重跑', value: retryRequiredTasks}] : []),
          ...(budgetStops.length ? [{label: '额度触发', value: budgetStops.length}] : []),
        ],
      };
    }

    function formatVerifySummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '验证邮箱',
          title: '已完成',
          lines: ['邮箱验证已完成。'],
        };
      }
      const attempted = Number(result.attempted || 0);
      const valid = Number(result.valid || 0);
      const invalid = Number(result.invalid || 0);
      const other = Number(result.other || 0);
      const errors = Number(result.errors || 0);
      const dedupedTasks = Number(result.deduped_tasks || 0);
      const retryRequiredTasks = Number(result.retry_required_tasks || 0);
      const budgetStops = Array.isArray(result.budget_stops) ? result.budget_stops : [];
      if (!attempted && !errors) {
        return {
          tone: budgetStops.length || retryRequiredTasks ? 'warn' : 'success',
          eyebrow: '验证邮箱',
          title: budgetStops.length ? '额度已触发' : retryRequiredTasks ? '存在待重跑任务' : '没有待验证邮箱',
          lines: [
            '邮箱验证已完成，本次没有需要验证的 Qualified 邮箱。',
            dedupedTasks > 0 ? `已跳过 ${dedupedTasks} 个已完成任务。` : '',
            retryRequiredTasks > 0 ? `${retryRequiredTasks} 个失败任务需要先标记重跑。` : '',
            budgetStops.length ? budgetStops.map((item) => item.message || '').filter(Boolean).join('；') : '',
          ].filter(Boolean),
          metrics: [
            {label: '验证', value: attempted},
            {label: '错误', value: errors},
            ...(dedupedTasks ? [{label: '去重跳过', value: dedupedTasks}] : []),
            ...(retryRequiredTasks ? [{label: '待重跑', value: retryRequiredTasks}] : []),
          ],
        };
      }
      return {
        tone: errors > 0 || budgetStops.length || retryRequiredTasks ? 'warn' : 'success',
        eyebrow: '验证邮箱',
        title: `已完成，共验证 ${attempted} 条`,
        lines: [
          `有效 ${valid} 条，无效 ${invalid} 条，其它结果 ${other} 条。`,
          errors > 0 ? `验证错误 ${errors} 条。` : '没有验证错误。',
          dedupedTasks > 0 ? `已跳过 ${dedupedTasks} 个已完成任务，避免重复扣费。` : '',
          retryRequiredTasks > 0 ? `${retryRequiredTasks} 个失败任务需要先标记重跑。` : '',
          budgetStops.length ? `额度保护已触发：${budgetStops.map((item) => item.message || '').filter(Boolean).join('；')}` : '',
        ].filter(Boolean),
        metrics: [
          {label: '验证', value: attempted},
          {label: '有效', value: valid},
          {label: '无效', value: invalid},
          {label: '其它', value: other},
          ...(dedupedTasks ? [{label: '去重跳过', value: dedupedTasks}] : []),
          ...(retryRequiredTasks ? [{label: '待重跑', value: retryRequiredTasks}] : []),
          ...(budgetStops.length ? [{label: '额度触发', value: budgetStops.length}] : []),
        ],
      };
    }

    function formatPullFeedbackSummary(result) {
      if (!result || typeof result !== 'object') {
        return {
          tone: 'success',
          eyebrow: '拉取反馈',
          title: '已完成',
          lines: ['拉取 CRM 反馈已完成。'],
        };
      }
      const matched = Number(result.matched || 0);
      const updated = Number(result.updated || 0);
      const unmatched = Number(result.unmatched || 0);
      const errors = Number(result.errors || 0);
      const outcomes = result.outcomes || {};
      if (!matched && !unmatched && !errors) {
        return {
          tone: 'success',
          eyebrow: '拉取反馈',
          title: '没有可处理线索',
          lines: ['拉取 CRM 反馈已完成，本次没有可处理的线索。'],
          metrics: [
            {label: '匹配', value: matched},
            {label: '未匹配', value: unmatched},
          ],
        };
      }
      return {
        tone: errors > 0 ? 'warn' : 'success',
        eyebrow: '拉取反馈',
        title: `已完成，匹配 ${matched} 条`,
        lines: [
          `本次更新 ${updated} 条，未匹配 ${unmatched} 条。`,
          `反馈结果：有效客户 ${Number(outcomes.valid_customer || 0)} 条，非买家 ${Number(outcomes.not_buyer || 0)} 条，错市场 ${Number(outcomes.wrong_market || 0)} 条，重复 ${Number(outcomes.duplicate || 0)} 条，无回复 ${Number(outcomes.no_response || 0)} 条，勿联系 ${Number(outcomes.do_not_contact || 0)} 条。`,
          errors > 0 ? `处理错误 ${errors} 条。` : '没有处理错误。',
        ],
        metrics: [
          {label: '匹配', value: matched},
          {label: '更新', value: updated},
          {label: '有效客户', value: Number(outcomes.valid_customer || 0)},
          {label: '勿联系', value: Number(outcomes.do_not_contact || 0)},
        ],
      };
    }

    function providerTaskStateLabel(task) {
      if (!task || typeof task !== 'object') return '—';
      if (Number(task.retry_requested || 0)) {
        if (task.retry_marked_at) {
          return `已标记重跑 · ${task.retry_marked_at}`;
        }
        return '已标记重跑';
      }
      return stateLabel(task.status || '');
    }

    function providerTaskSummaryText(rows, scope) {
      const total = rows.length;
      if (!total) {
        if (scope === 'marked') return '当前没有已标记重跑的任务。';
        if (scope === 'all') return '当前还没有记录到付费任务。';
        return '当前没有失败或中断的付费任务。';
      }
      const marked = rows.filter((row) => Number(row.retry_requested || 0)).length;
      const failed = rows.filter((row) => String(row.status || '').toLowerCase() === 'error').length;
      const running = rows.filter((row) => String(row.status || '').toLowerCase() === 'running').length;
      return `共 ${total} 条，其中失败 ${failed} 条，中断 ${running} 条，已标记重跑 ${marked} 条。`;
    }

    function updateProviderTaskStatus(text) {
      const element = document.getElementById('provider-task-status');
      if (element) element.textContent = text;
    }

    function syncProviderTaskSelectAll() {
      const rows = Array.from(document.querySelectorAll('input[data-provider-task-id]'));
      const selectAll = document.getElementById('provider-task-select-all');
      if (!selectAll) return;
      if (!rows.length) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
        return;
      }
      const selectedCount = rows.filter((input) => input.checked).length;
      selectAll.checked = selectedCount === rows.length;
      selectAll.indeterminate = selectedCount > 0 && selectedCount < rows.length;
    }

    function onProviderTaskSelectionChange(event) {
      const input = event.target;
      const taskId = Number(input.getAttribute('data-provider-task-id') || 0);
      if (!taskId) return;
      if (input.checked) {
        selectedProviderTaskIds.add(taskId);
      } else {
        selectedProviderTaskIds.delete(taskId);
      }
      syncProviderTaskSelectAll();
    }

    function onProviderTaskSelectAllChange(event) {
      const checked = Boolean(event.target.checked);
      document.querySelectorAll('input[data-provider-task-id]').forEach((input) => {
        const taskId = Number(input.getAttribute('data-provider-task-id') || 0);
        input.checked = checked;
        if (!taskId) return;
        if (checked) {
          selectedProviderTaskIds.add(taskId);
        } else {
          selectedProviderTaskIds.delete(taskId);
        }
      });
      syncProviderTaskSelectAll();
    }

    async function loadProviderTasks() {
      const provider = document.getElementById('provider-task-provider').value;
      const scope = document.getElementById('provider-task-scope').value;
      updateProviderTaskStatus('正在刷新失败任务...');
      const params = new URLSearchParams({limit: '100', scope});
      if (provider) params.set('provider', provider);
      const response = await fetch(`/api/provider-tasks?${params.toString()}`);
      const payload = await response.json();
      const rows = Array.isArray(payload.tasks) ? payload.tasks : [];
      const tbody = document.getElementById('provider-task-report');
      const nextSelection = new Set();
      if (!rows.length) {
        selectedProviderTaskIds.clear();
        tbody.innerHTML = '<tr><td class="empty" colspan="10">当前没有可显示的失败任务。</td></tr>';
        syncProviderTaskSelectAll();
        updateProviderTaskStatus(providerTaskSummaryText(rows, scope));
        return;
      }
      tbody.innerHTML = rows.map((task) => {
        const taskId = Number(task.id || 0);
        const isSelected = selectedProviderTaskIds.has(taskId);
        if (isSelected) nextSelection.add(taskId);
        const lastResult = task.last_error || task.last_message || '';
        return `
          <tr>
            <td class="task-checkbox"><input type="checkbox" data-provider-task-id="${taskId}" ${isSelected ? 'checked' : ''} aria-label="选择任务 ${taskId}"></td>
            <td>${esc(task.provider)}</td>
            <td>${esc(task.task_type)}</td>
            <td>${task.lead_id ? `#${task.lead_id}` : '—'}</td>
            <td class="state">${esc(stateLabel(task.status))}</td>
            <td class="state">${esc(providerTaskStateLabel(task))}</td>
            <td>${Number(task.attempts || 0)}</td>
            <td class="task-key">${esc(task.task_key)}</td>
            <td class="task-message">${esc(lastResult || '—')}</td>
            <td class="state">${esc(task.updated_at || '')}</td>
          </tr>
        `;
      }).join('');
      selectedProviderTaskIds.clear();
      nextSelection.forEach((taskId) => selectedProviderTaskIds.add(taskId));
      tbody.querySelectorAll('input[data-provider-task-id]').forEach((input) => {
        input.addEventListener('change', onProviderTaskSelectionChange);
      });
      syncProviderTaskSelectAll();
      updateProviderTaskStatus(providerTaskSummaryText(rows, scope));
    }

    async function markSelectedProviderTasksRetry() {
      const button = document.getElementById('provider-task-mark-retry');
      const taskIds = Array.from(selectedProviderTaskIds);
      clearActionButtonStates(button.id);
      if (!taskIds.length) {
        renderActionSummary(button.id, formatProviderTaskRetrySummary({selected: 0, marked: 0, eligible: 0}));
        return;
      }
      button.disabled = true;
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '标记重跑',
        title: '正在更新',
        lines: ['正在给选中的失败任务加上重跑标记...'],
      });
      try {
        const response = await fetch('/api/mark-provider-retry', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({task_ids: taskIds})
        });
        const payload = await response.json();
        renderActionSummary(button.id, formatProviderTaskRetrySummary(payload.result || payload));
        await loadProviderTasks();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('标记重跑', error));
      } finally {
        button.disabled = false;
      }
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
      syncToolbarState();
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
        tbody.innerHTML = '<tr><td class="empty" colspan="14">当前视图没有线索。</td></tr>';
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
          lead.score_explanation ? `评分依据: ${lead.score_explanation}` : '',
          lead.crm_followup_status ? `CRM跟进: ${lead.crm_followup_status}` : '',
          lead.crm_last_contact_at ? `CRM最近联系: ${lead.crm_last_contact_at}` : ''
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
            <td class="state">${esc(stateLabel(lead.crm_outcome))}</td>
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
      if (!state.hunter) {
        setActionButtonState('enrich-qualified', 'idle');
        setActionButtonState('verify-qualified', 'idle');
      }
    }

    async function loadUsage() {
      const response = await fetch('/api/usage');
      const payload = await response.json();
      const usage = payload.usage || {};
      const daily = payload.daily_usage || {};
      const budgets = payload.budgets || {};
      setUsageLabel('usage-serper', usage.Serper || 0, daily.Serper || 0, budgets.Serper || {});
      setUsageLabel('usage-hunter', usage['Hunter.io'] || 0, daily['Hunter.io'] || 0, budgets['Hunter.io'] || {});
      setUsageLabel('usage-apollo', usage['Apollo.io'] || 0, daily['Apollo.io'] || 0, budgets['Apollo.io'] || {});
    }

    function setUsageLabel(elementId, latest, daily, budget) {
      const element = document.getElementById(elementId);
      if (!element) return;
      const latestText = Number(latest || 0);
      const dailyText = Number(daily || 0);
      const dailyLimit = Number((budget || {}).daily_limit || 0);
      element.textContent = dailyLimit > 0
        ? `${latestText} · 今日 ${dailyText}/${dailyLimit}`
        : `${latestText} · 今日 ${dailyText}`;
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

    async function loadCrmFeedbackReport() {
      const response = await fetch('/api/crm-feedback-report');
      const payload = await response.json();
      const rows = payload.rows || [];
      const tbody = document.getElementById('crm-feedback-report');
      if (!rows.length) {
        tbody.innerHTML = '<tr><td class="empty" colspan="11">暂无 CRM 反馈。</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map((row) => `
        <tr>
          <td>${esc(row.country)}</td>
          <td>${esc(productFamilyLabel(row.product_family))}</td>
          <td>${esc(stateLabel(row.classification_status))}</td>
          <td class="reason">${esc(row.discovery_query || '')}</td>
          <td>${row.valid_customer || 0}</td>
          <td>${row.not_buyer || 0}</td>
          <td>${row.wrong_market || 0}</td>
          <td>${row.duplicate || 0}</td>
          <td>${row.no_response || 0}</td>
          <td>${row.do_not_contact || 0}</td>
          <td>${esc(stateLabel(row.suggestion))}</td>
        </tr>
      `).join('');
    }

    async function loadCrmState() {
      const response = await fetch('/api/crm-state');
      const payload = await response.json();
      const available = Boolean(payload.available);
      document.getElementById('crm-state').textContent = available ? 'CRM 已连接' : 'CRM 未连接';
      document.getElementById('sync-crm').disabled = !available;
      document.getElementById('pull-crm-feedback').disabled = !available;
      if (!available) {
        setActionButtonState('sync-crm', 'idle');
        setActionButtonState('pull-crm-feedback', 'idle');
      }
    }

    async function runCampaign() {
      const button = document.getElementById('run-campaign');
      const countries = Array.from(selectedCountries);
      if (!countries.length) {
        clearActionButtonStates(button.id);
        renderActionSummary(button.id, {
          tone: 'warn',
          eyebrow: '自动搜寻',
          title: '无法执行',
          lines: ['请先选择至少 1 个目标国家。'],
        });
        return;
      }
      button.disabled = true;
      clearActionButtonStates(button.id);
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '自动搜寻',
        title: '正在运行',
        lines: ['正在自动搜寻，会消耗已启用 API 的额度，建议先用小批量验证。'],
      });
      try {
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
        renderActionSummary(button.id, formatCampaignSummary(payload.result || payload));
        await loadLeads();
        await loadRecallReport(payload.result ? payload.result.run_id : '');
        await loadUsage();
        await loadProviderTasks();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('自动搜寻', error));
      } finally {
        button.disabled = false;
      }
    }

    async function requalifyExistingLeads() {
      const button = document.getElementById('requalify');
      button.disabled = true;
      clearActionButtonStates(button.id);
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '批量复核',
        title: '正在运行',
        lines: ['正在重新抓取并复核旧线索...'],
      });
      try {
        const response = await fetch('/api/requalify', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 100, only_unreviewed: true, min_score: 50})
        });
        const payload = await response.json();
        renderActionSummary(button.id, formatRequalifySummary(payload.result || payload));
        await loadLeads();
        await loadProviderTasks();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('批量复核', error));
      } finally {
        button.disabled = false;
      }
    }

    async function enrichQualifiedEmails() {
      const button = document.getElementById('enrich-qualified');
      button.disabled = true;
      clearActionButtonStates(button.id);
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '补全邮箱',
        title: '正在运行',
        lines: ['正在为已确认线索查询并验证邮箱...'],
      });
      try {
        const response = await fetch('/api/enrich-qualified', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 5})
        });
        const payload = await response.json();
        renderActionSummary(button.id, formatEnrichSummary(payload.result || payload));
        await loadLeads();
        await loadProviderTasks();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('补全邮箱', error));
      } finally {
        await loadProviderState();
      }
    }

    async function verifyQualifiedEmails() {
      const button = document.getElementById('verify-qualified');
      button.disabled = true;
      clearActionButtonStates(button.id);
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '验证邮箱',
        title: '正在运行',
        lines: ['正在验证 Qualified 线索已有邮箱...'],
      });
      try {
        const response = await fetch('/api/verify-qualified-emails', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 10})
        });
        const payload = await response.json();
        renderActionSummary(button.id, formatVerifySummary(payload.result || payload));
        await loadLeads();
        await loadProviderTasks();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('验证邮箱', error));
      } finally {
        await loadProviderState();
      }
    }

    async function syncCrm() {
      const button = document.getElementById('sync-crm');
      button.disabled = true;
      clearActionButtonStates(button.id);
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '同步 CRM',
        title: '正在运行',
        lines: ['正在将已验证的 Qualified 线索同步到 CRM...'],
      });
      try {
        const response = await fetch('/api/sync-crm', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 50})
        });
        const payload = await response.json();
        renderActionSummary(button.id, formatSyncCrmSummary(payload.result || payload));
        await loadLeads();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('同步 CRM', error));
      } finally {
        await loadCrmState();
      }
    }

    async function pullCrmFeedback() {
      const button = document.getElementById('pull-crm-feedback');
      button.disabled = true;
      clearActionButtonStates(button.id);
      setActionButtonState(button.id, 'working');
      renderSummaryCard({
        tone: 'working',
        eyebrow: '拉取反馈',
        title: '正在运行',
        lines: ['正在从 CRM 拉取跟进反馈...'],
      });
      try {
        const response = await fetch('/api/pull-crm-feedback', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({limit: 500})
        });
        const payload = await response.json();
        renderActionSummary(button.id, formatPullFeedbackSummary(payload.result || payload));
        await loadLeads();
        await loadCrmFeedbackReport();
      } catch (error) {
        renderActionSummary(button.id, formatActionError('拉取反馈', error));
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
    document.getElementById('provider-task-refresh').addEventListener('click', loadProviderTasks);
    document.getElementById('provider-task-provider').addEventListener('change', loadProviderTasks);
    document.getElementById('provider-task-scope').addEventListener('change', loadProviderTasks);
    document.getElementById('provider-task-select-all').addEventListener('change', onProviderTaskSelectAllChange);
    document.getElementById('provider-task-mark-retry').addEventListener('click', markSelectedProviderTasksRetry);
    document.getElementById('sync-crm').addEventListener('click', syncCrm);
    document.getElementById('pull-crm-feedback').addEventListener('click', pullCrmFeedback);
    renderMarketPicker();
    syncToolbarState();
    renderSummaryCard();
    loadProviderState();
    loadUsage();
    loadProviderTasks();
    loadRecallReport();
    loadCrmFeedbackReport();
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


def _start_action_log(db, run_type: str, metadata: dict | None = None) -> dict:
    return create_run_log(
        db,
        run_type,
        trigger_source="webapp",
        metadata=metadata or {},
    )


def _finish_action_log(db, run_log_id: int, *, status: str, result: dict, error_summary: str = "") -> dict:
    return finish_run_log(
        db,
        run_log_id,
        status=status,
        success_count=int(result.get("synced") or result.get("updated") or result.get("verified") or result.get("valid") or result.get("created") or result.get("reviewed") or 0),
        failure_count=int(result.get("errors") or 0),
        skipped_count=int(result.get("skipped") or result.get("duplicates") or result.get("no_email") or result.get("skipped_unverified") or result.get("unmatched") or result.get("other") or 0),
        error_summary=error_summary,
        metadata=result,
    )


def _record_summary_usage(db, run_log_id: int, provider: str, event_type: str, summary: dict) -> None:
    cost_units = 0.0
    if provider == "CRM" and event_type == "sync":
        cost_units = float(summary.get("attempted", 0) or 0)
    elif provider == "CRM" and event_type == "pull_feedback":
        cost_units = float(summary.get("matched", 0) or 0)
    record_run_usage(
        db,
        run_log_id,
        provider=provider,
        event_type=event_type,
        status="ok" if not int(summary.get("errors") or 0) else "warn",
        cost_units=cost_units,
        message=json.dumps(summary, ensure_ascii=False),
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
            cfg = settings()
            db = connect(self.db_path)
            try:
                payload = latest_provider_usage(db)
                payload["daily_usage"] = daily_run_usage(db, providers=["Serper", "Hunter.io", "Apollo.io"])
                payload["budgets"] = budget_snapshot(
                    db,
                    cfg,
                    payload.get("run", {}).get("id") if isinstance(payload.get("run"), dict) else None,
                )
            finally:
                db.close()
            return self.json_response(payload)

        if method == "GET" and parsed.path == "/api/provider-tasks":
            query = parse_qs(parsed.query, keep_blank_values=True)
            provider = str(query.get("provider", [""])[0] or "").strip() or None
            scope = str(query.get("scope", ["failed"])[0] or "failed").strip().lower()
            limit_text = query.get("limit", ["50"])[0]
            try:
                limit = max(1, min(int(limit_text or 50), 200))
            except (TypeError, ValueError):
                return self.json_response({"error": "invalid limit"}, status=400)
            if scope not in {"failed", "marked", "all"}:
                return self.json_response({"error": "invalid scope"}, status=400)
            db = connect(self.db_path)
            try:
                rows = list_provider_tasks(db, provider=provider, limit=limit)
                if scope == "failed":
                    rows = [
                        row for row in rows
                        if str(row.get("status") or "").lower() in {"error", "running"}
                    ]
                elif scope == "marked":
                    rows = [row for row in rows if int(row.get("retry_requested") or 0)]
            finally:
                db.close()
            return self.json_response({"tasks": rows, "scope": scope})

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

        if method == "GET" and parsed.path == "/api/crm-feedback-report":
            db = connect(self.db_path)
            try:
                payload = crm_feedback_report(db)
            finally:
                db.close()
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
                    budget_limits=budget_limits_from_settings(cfg),
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
                run_log = _start_action_log(db, "requalify", {"limit": options.limit, "min_score": options.min_score})
                result = requalify_leads(db, options)
                _finish_action_log(db, run_log["id"], status="Completed", result=result)
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
                run_log = _start_action_log(db, "enrich_qualified", {"limit": limit})
                budget_manager = BudgetManager(db, run_log["id"], budget_limits_from_settings(cfg))
                result = enrich_qualified_emails(
                    db,
                    HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds),
                    limit=limit,
                    budget_manager=budget_manager,
                )
                _finish_action_log(
                    db,
                    run_log["id"],
                    status="Completed",
                    result=result,
                    error_summary="; ".join(item.get("message", "") for item in result.get("budget_stops", []) if item.get("message")),
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
                run_log = _start_action_log(db, "verify_qualified_emails", {"limit": limit})
                budget_manager = BudgetManager(db, run_log["id"], budget_limits_from_settings(cfg))
                result = verify_existing_qualified_emails(
                    db,
                    HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds),
                    limit=limit,
                    budget_manager=budget_manager,
                )
                _finish_action_log(
                    db,
                    run_log["id"],
                    status="Completed",
                    result=result,
                    error_summary="; ".join(item.get("message", "") for item in result.get("budget_stops", []) if item.get("message")),
                )
            finally:
                db.close()
            return self.json_response({"result": result})

        if method == "POST" and parsed.path == "/api/mark-provider-retry":
            payload = json.loads(body.decode("utf-8") or "{}")
            raw_task_ids = payload.get("task_ids", [])
            if not isinstance(raw_task_ids, list):
                return self.json_response({"error": "task_ids must be a list"}, status=400)
            task_ids: list[int] = []
            for item in raw_task_ids:
                try:
                    task_id = int(item)
                except (TypeError, ValueError):
                    return self.json_response({"error": "invalid task id"}, status=400)
                if task_id > 0:
                    task_ids.append(task_id)
            db = connect(self.db_path)
            try:
                run_log = _start_action_log(
                    db,
                    "mark_provider_retry",
                    {"selected": len(task_ids), "task_ids": task_ids},
                )
                tracked_rows = list_provider_tasks_by_ids(db, task_ids)
                eligible_ids = {
                    int(row["id"])
                    for row in tracked_rows
                    if str(row.get("status") or "").lower() in {"error", "running"}
                }
                already_marked_ids = {
                    int(row["id"])
                    for row in tracked_rows
                    if int(row.get("retry_requested") or 0)
                }
                rows = mark_provider_task_ids_for_retry(db, task_ids, marked_by="webapp")
                marked_ids = {
                    int(row["id"])
                    for row in rows
                    if int(row.get("id") or 0) in eligible_ids
                    and int(row.get("retry_requested") or 0)
                    and int(row.get("id") or 0) not in already_marked_ids
                }
                result = {
                    "selected": len(task_ids),
                    "eligible": len(eligible_ids),
                    "marked": len(marked_ids),
                    "already_marked": len(already_marked_ids & eligible_ids),
                    "not_eligible": max(0, len(task_ids) - len(eligible_ids)),
                    "tasks": rows,
                    "errors": 0,
                }
                _finish_action_log(db, run_log["id"], status="Completed", result=result)
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
                run_log = _start_action_log(db, "sync_crm", {"limit": limit})
                result = sync_verified_qualified(
                    db,
                    cfg.crm_url,
                    limit=limit,
                    timeout=min(cfg.timeout_seconds, 8.0),
                )
                _record_summary_usage(db, run_log["id"], "CRM", "sync", result)
                _finish_action_log(db, run_log["id"], status="Completed", result=result)
            finally:
                db.close()
            return self.json_response({"result": result})

        if method == "POST" and parsed.path == "/api/pull-crm-feedback":
            cfg = settings()
            payload = json.loads(body.decode("utf-8") or "{}")
            raw_limit = payload.get("limit")
            limit = None if raw_limit in (None, "", 0) else max(1, min(int(raw_limit), 1000))
            try:
                crm_status(cfg.crm_url, timeout=min(cfg.timeout_seconds, 3.0))
            except Exception as error:
                return self.json_response(
                    {"error": sanitize_error(error)},
                    status=503,
                )
            db = connect(self.db_path)
            try:
                run_log = _start_action_log(db, "pull_crm_feedback", {"limit": limit})
                result = pull_crm_feedback(
                    db,
                    cfg.crm_url,
                    limit=limit,
                    timeout=min(cfg.timeout_seconds, 8.0),
                )
                _record_summary_usage(db, run_log["id"], "CRM", "pull_feedback", result)
                _finish_action_log(db, run_log["id"], status="Completed", result=result)
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
