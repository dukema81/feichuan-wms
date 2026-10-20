/* 飞传 WMS · 前端框架、仓储驾驶舱、基础设置与操作日志（原生 JS，零依赖） */
(function (window, document) {
  "use strict";

  var F = window.F = {};
  var TOKEN_KEY = "wms_token";

  F.state = { boot: null, route: "dashboard", params: {}, timer: null };

  /* ---------------------------------------------------------- 基础工具 */
  F.esc = function (s) {
    return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  F.num = function (v, d) {
    var n = Number(v || 0);
    return n.toLocaleString("zh-CN", { minimumFractionDigits: d === undefined ? 2 : d,
      maximumFractionDigits: d === undefined ? 2 : d });
  };
  F.int = function (v) { return F.num(v, 0); };
  F.qty = function (v) {
    var n = Number(v || 0);
    return Number.isInteger(n) ? F.int(n) : F.num(n, 1);
  };
  F.wan = function (v) {
    var n = Number(v || 0);
    return Math.abs(n) >= 10000 ? (n / 10000).toFixed(1) + " 万" : F.num(n, 0);
  };
  F.pct = function (v, d) {
    var n = Number(v || 0) * 100;
    return n.toFixed(d === undefined ? 1 : d) + "%";
  };
  F.cube = function (v) {
    var n = Number(v || 0);
    return n >= 1 ? n.toFixed(1) + " m³" : (n * 1000).toFixed(0) + " L";
  };
  F.today = function () { return new Date().toISOString().slice(0, 10); };
  F.qs = function (o) {
    return Object.keys(o || {}).filter(function (k) { return o[k] !== undefined && o[k] !== null; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(o[k]); }).join("&");
  };
  F.dash = function (v) { return v === null || v === undefined || v === "" ? "—" : v; };

  var TAGS = {
    // 入库
    "草稿": "gray", "已预约": "blue", "已到货": "gold", "收货中": "gold",
    "已收货": "blue", "已上架": "green", "已关闭": "gray", "已取消": "gray",
    // 出库
    "已提交": "blue", "已分配": "blue", "拣货中": "gold", "已拣货": "gold",
    "已复核": "green", "已发运": "green", "已签收": "green",
    // 盘点 / 任务
    "盘点中": "gold", "待审核": "gold", "已调整": "green", "待拣": "gold", "已拣": "green",
    "待执行": "gold", "已完成": "green", "待盘": "gold", "已盘": "green",
    // 效期与水位
    "已过期": "red", "临期": "gold", "关注": "blue", "正常": "green",
    "充足": "green", "偏低": "gold", "不足": "red", "断货": "red",
    "盘平": "green", "盘盈": "blue", "盘亏": "red",
    // 异常与优先级
    "待处理": "red", "处理中": "gold",
    "特急": "red", "加急": "gold", "普通": "gray",
    "高": "red", "中": "gold", "低": "gray",
    // 状态通用
    "启用": "green", "停用": "gray", "吊销": "red", "禁用": "gray",
    "成功": "green", "失败": "red", "待投递": "gold",
    "运行": "green", "空闲": "gray", "占用": "blue", "锁定": "gold",
    "A": "green", "B": "blue", "C": "gold"
  };
  F.TAGS = TAGS;
  F.tag = function (s, cls) {
    return '<span class="tag ' + (cls || TAGS[s] || "gray") + '">' + F.esc(s) + "</span>";
  };
  F.prio = function (p) { return F.tag(p, p === "特急" ? "red" : (p === "加急" ? "gold" : "gray")); };

  /* ---------------------------------------------------------- 请求 */
  F.raw = function (method, path, body, headers) {
    var h = { "Content-Type": "application/json" };
    var tk = localStorage.getItem(TOKEN_KEY);
    if (tk) { h.Authorization = "Bearer " + tk; h["X-Fc-Token"] = tk; }
    Object.keys(headers || {}).forEach(function (k) { h[k] = headers[k]; });
    var opt = { method: method, headers: h, credentials: "same-origin" };
    if (body !== undefined && body !== null) opt.body = JSON.stringify(body);
    return fetch(path.replace(/^\//, ""), opt).then(function (r) {
      return r.json().catch(function () { return { error: "响应解析失败" }; })
        .then(function (j) { return { status: r.status, body: j }; });
    });
  };

  F.api = function (method, path, body) {
    return F.raw(method, path, body).then(function (x) {
      if (x.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        location.href = "./login.html";
        return new Promise(function () {});
      }
      if (x.status >= 400) {
        var e = new Error((x.body && x.body.error) || ("请求失败 " + x.status));
        e.status = x.status;
        e.body = x.body;
        throw e;
      }
      return x.body.data;
    });
  };

  F.toast = function (msg, kind) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    el.textContent = msg;
    F._toastUntil = Date.now() + 6000;
    el.style.color = kind === "err" ? "#ffb3a7" : (kind === "ok" ? "#9ee6b8" : "");
    clearTimeout(F._t);
    F._t = setTimeout(function () { el.style.color = ""; }, 8000);
  };
  F.setStatus = function (t) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    if (F._toastUntil && Date.now() < F._toastUntil) return;
    el.textContent = t;
  };
  F.setSide = function (html) { var el = document.getElementById("side"); if (el) el.innerHTML = html; };

  F.can = function (perm) {
    var b = F.state.boot;
    return !!(b && b.user && (b.user.perms || []).indexOf(perm) >= 0);
  };
  F.isAdmin = function () { return F.state.boot && F.state.boot.user.role === "admin"; };
  F.me = function () { return (F.state.boot && F.state.boot.user) || {}; };

  /* ---------------------------------------------------------- 路由 */
  function parseHash() {
    var h = (location.hash || "#dashboard").replace(/^#\/?/, "");
    var i = h.indexOf("?");
    var route = i < 0 ? h : h.slice(0, i);
    var qs = i < 0 ? "" : h.slice(i + 1);
    var params = {};
    qs.split("&").forEach(function (kv) {
      if (!kv) return;
      var j = kv.indexOf("=");
      params[decodeURIComponent(j < 0 ? kv : kv.slice(0, j))] =
        decodeURIComponent(j < 0 ? "" : kv.slice(j + 1));
    });
    return { route: route || "dashboard", params: params };
  }

  F.go = function (route, params) {
    location.hash = "#" + route + (params && Object.keys(params).length ? "?" + F.qs(params) : "");
  };

  var PAGES = {};
  F.register = function (name, fn) { PAGES[name] = fn; };

  function render() {
    var r = parseHash();
    F.state.route = r.route;
    F.state.params = r.params;
    if (F.state.timer) { clearInterval(F.state.timer); F.state.timer = null; }
    var fn = PAGES[r.route] || PAGES.dashboard;
    var view = document.getElementById("view");
    view.innerHTML = "";
    paintNav(r.route);
    try {
      fn(r.params);
    } catch (e) {
      view.innerHTML = '<div class="panel"><div class="panel-body">页面渲染失败：' +
        F.esc(e.message) + "</div></div>";
    }
  }
  F.render = render;

  /* ---------------------------------------------------------- 导航 */
  var TREE = [
    { grp: "作业执行", items: [["dashboard", "仓储驾驶舱"], ["inbound", "入库作业"],
      ["outbound", "出库作业"], ["wave", "波次拣货"], ["stocktake", "盘点作业"]] },
    { grp: "库存管理", items: [["stock", "库存台账"], ["locations", "库位管理"],
      ["replenish", "补货移库"], ["trace", "批次追溯"]] },
    { grp: "主数据", items: [["items", "物料主数据"], ["partners", "往来单位"]] },
    { grp: "分析", items: [["reports", "报表分析"]] },
    { grp: "系统", items: [["integration", "集成中心"], ["settings", "基础设置"],
      ["logs", "操作日志"]] }
  ];

  var MENU = TREE.map(function (g) { return [g.grp, g.items.map(function (i) { return i[0]; })]; });

  var TITLE = {
    dashboard: "仓储驾驶舱", inbound: "入库作业", outbound: "出库作业", wave: "波次拣货",
    stocktake: "盘点作业", stock: "库存台账", locations: "库位管理", replenish: "补货移库",
    trace: "批次追溯", items: "物料主数据", partners: "往来单位", reports: "报表分析",
    integration: "集成中心", settings: "基础设置", logs: "操作日志"
  };
  F.TITLE = TITLE;

  function paintNav(route) {
    var tree = document.getElementById("tree");
    var boot = F.state.boot || {};
    var kpi = boot.kpi || {};
    var badgeFor = {
      dashboard: (boot.todo || []).length,
      inbound: kpi.waitReceive || 0,
      outbound: kpi.soOpen || 0,
      wave: kpi.waveOpen || 0,
      replenish: kpi.replenishOpen || 0,
      stock: kpi.expiryWarn || 0
    };
    tree.innerHTML = TREE.map(function (g) {
      return '<div class="grp">' + F.esc(g.grp) + "</div>" + g.items.map(function (it) {
        var n = badgeFor[it[0]] || 0;
        var badge = n ? '<b class="nav-badge">' + n + "</b>" : "";
        return '<a href="#' + it[0] + '" class="' + (it[0] === route ? "on" : "") + '">' +
          F.esc(it[1]) + badge + "</a>";
      }).join("");
    }).join("");

    var mb = document.getElementById("menubar");
    var groupOf = {};
    MENU.forEach(function (m) { m[1].forEach(function (r) { groupOf[r] = m[0]; }); });
    mb.innerHTML = MENU.map(function (m) {
      return '<button class="' + (groupOf[route] === m[0] ? "on" : "") + '" data-group="' +
        F.esc(m[0]) + '">' + F.esc(m[0]) + "</button>";
    }).join("");
    mb.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        var g = b.getAttribute("data-group");
        var target = MENU.filter(function (m) { return m[0] === g; })[0];
        if (target) F.go(target[1][0]);
      });
    });

    var ts = document.getElementById("tabstrip");
    ts.innerHTML = '<span class="tab">' + F.esc(TITLE[route] || route) + "</span>" +
      '<span class="muted small">飞传 WMS / ' + F.esc(TITLE[route] || route) + "</span>";
  }

  /* ---------------------------------------------------------- 通用渲染 */
  F.table = function (headers, rows, opts) {
    opts = opts || {};
    var th = headers.map(function (h) {
      return "<th class='" + (h.num ? "num" : "") + "'" +
        (h.width ? " style='width:" + h.width + "'" : "") + ">" + F.esc(h.label) + "</th>";
    }).join("");
    var body = rows && rows.length ? rows.map(function (r, i) {
      return '<tr class="' + (opts.click ? "clickable" : "") + '"' +
        (opts.click ? " data-key='" + F.esc(opts.click(r, i)) + "'" : "") + ">" +
        headers.map(function (h) {
          var v = h.render ? h.render(r, i) : F.esc(r[h.key]);
          return "<td class='" + (h.num ? "num" : "") + "'>" + v + "</td>";
        }).join("") + "</tr>";
    }).join("") : '<tr class="empty-row"><td colspan="' + headers.length + '">' +
      F.esc(opts.empty || "暂无数据") + "</td></tr>";
    return "<table class='grid-table'><thead><tr>" + th + "</tr></thead><tbody>" + body + "</tbody></table>";
  };

  F.bindRows = function (root, fn) {
    (root || document).querySelectorAll("#view tbody tr[data-key]").forEach(function (tr) {
      tr.addEventListener("click", function () { fn(tr.getAttribute("data-key"), tr); });
    });
  };

  F.dialog = function (title, body, foot) {
    var mask = document.getElementById("mask");
    var dlg = document.getElementById("dialog");
    dlg.className = "dialog" + (F._wide ? " wide" : "");
    F._wide = false;
    dlg.innerHTML = '<div class="dh">' + F.esc(title) +
      '<span class="x" data-close="1">×</span></div><div class="db">' + body + "</div>" +
      (foot ? '<div class="df">' + foot + "</div>" : "");
    mask.className = "mask on";
    dlg.querySelector("[data-close]").addEventListener("click", F.closeDialog);
    return dlg;
  };
  F.dialogWide = function (title, body, foot) { F._wide = true; return F.dialog(title, body, foot); };
  F.closeDialog = function () { document.getElementById("mask").className = "mask"; };
  F.dialogOpen = function () {
    return document.getElementById("mask").className.indexOf("on") >= 0;
  };

  F.chips = function (items, active, attr) {
    return '<div class="chips">' + items.map(function (it) {
      var val = typeof it === "string" ? it : it[0];
      var label = typeof it === "string" ? it : it[1];
      var count = typeof it === "string" ? "" : (
        it[2] === undefined || it[2] === null ? "" : '<span class="chip-n">' + it[2] + "</span>");
      return '<button class="chip' + (val === active ? " on" : "") + '" ' + (attr || "data-st") +
        '="' + F.esc(val) + '">' + F.esc(label) + count + "</button>";
    }).join("") + "</div>";
  };

  F.lineChart = function (series, opts) {
    opts = opts || {};
    var W = opts.width || 640, H = opts.height || 190, P = 34;
    var labels = opts.labels || [];
    var all = [];
    series.forEach(function (s) { all = all.concat(s.data); });
    var max = Math.max.apply(null, all.concat([1]));
    var min = opts.zero === false ? Math.min.apply(null, all) : 0;
    var span = max - min || 1;
    var colors = opts.colors || ["#1f7a8c", "#c8963e", "#b4463a"];
    var w = (W - P * 2) / Math.max(1, labels.length - 1);
    var grid = [0, 0.25, 0.5, 0.75, 1].map(function (t) {
      var y = P + (H - P * 1.6) * t;
      var val = max - span * t;
      return '<line x1="' + P + '" y1="' + y + '" x2="' + (W - P) + '" y2="' + y +
        '" stroke="#eef2f5"/><text x="6" y="' + (y + 4) + '" font-size="10" fill="#8b9aa6">' +
        (val >= 10000 ? (val / 10000).toFixed(1) + "万" : Math.round(val)) + "</text>";
    }).join("");
    var paths = series.map(function (s, si) {
      var d = s.data.map(function (v, i) {
        var x = P + w * i;
        var y = P + (H - P * 1.6) * (1 - (v - min) / span);
        return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      }).join(" ");
      return '<path d="' + d + '" fill="none" stroke="' + colors[si % colors.length] +
        '" stroke-width="2"/>' + s.data.map(function (v, i) {
          var x = P + w * i;
          var y = P + (H - P * 1.6) * (1 - (v - min) / span);
          return '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="2.6" fill="' +
            colors[si % colors.length] + '"/>';
        }).join("");
    }).join("");
    var xlabels = labels.map(function (t, i) {
      return '<text x="' + (P + w * i) + '" y="' + (H - 6) +
        '" font-size="10" fill="#8b9aa6" text-anchor="middle">' + F.esc(t) + "</text>";
    }).join("");
    var legend = series.map(function (s, si) {
      return '<span class="lg-dot"><i style="background:' + colors[si % colors.length] + '"></i>' +
        F.esc(s.name) + "</span>";
    }).join("");
    return '<div class="chart-legend">' + legend + "</div>" +
      '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">' +
      grid + paths + xlabels + "</svg>";
  };

  F.barChart = function (items, opts) {
    opts = opts || {};
    var W = opts.width || 640, H = opts.height || 180, P = 34;
    var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1]));
    var gap = (W - P * 2) / Math.max(1, items.length);
    var bw = gap * 0.56;
    return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">' +
      items.map(function (it, i) {
        var h = (H - P * 1.8) * (it.value / max);
        var x = P + gap * i + (gap - bw) / 2;
        var y = H - P - h;
        return '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
          '" height="' + Math.max(1, h).toFixed(1) + '" rx="2" fill="' + (it.color || "#2b9eb3") + '"/>' +
          '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 5) +
          '" font-size="10" fill="#5d6f7c" text-anchor="middle">' + F.esc(it.label2 || "") +
          "</text>" + '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 8) +
          '" font-size="10" fill="#8b9aa6" text-anchor="middle">' + F.esc(it.label) + "</text>";
      }).join("") + "</svg>";
  };

  /* 状态分布条 */
  F.stageBars = function (stages) {
    var max = Math.max.apply(null, stages.map(function (s) { return s.count; }).concat([1]));
    return '<div class="funnel">' + stages.map(function (s) {
      var w = Math.max(5, Math.round(s.count / max * 100));
      var color = TAGS[s.status] === "gold" ? "#c8963e" : (TAGS[s.status] === "green" ? "#2f8f5b" :
        (TAGS[s.status] === "red" ? "#b4463a" : "#2b7fa8"));
      return '<div class="fn-row"><div class="fn-name">' + F.esc(s.status) + "</div>" +
        '<div class="fn-bar"><i style="width:' + w + "%;background:" + color + '"></i></div>' +
        '<div class="fn-val">' + s.count + ' <span class="muted small">单</span></div>' +
        '<div class="fn-conv"></div></div>';
    }).join("") + "</div>";
  };

  /* 环形指标 */
  F.ring = function (v, opts) {
    opts = opts || {};
    var p = Math.max(0, Math.min(1, Number(v || 0)));
    var color = opts.color || (p >= 0.85 ? "#2f8f5b" : (p >= 0.6 ? "#c8963e" : "#b4463a"));
    var deg = (p * 360).toFixed(1);
    return '<div class="ring" style="background:conic-gradient(' + color + " 0deg " + deg +
      "deg,#eef2f5 " + deg + 'deg 360deg)"><div class="ring-in"><b>' + F.pct(p, opts.d === undefined ? 1 : opts.d) +
      "</b><span>" + F.esc(opts.label || "利用率") + "</span></div></div>";
  };

  F.empty = function (text) {
    return '<div class="empty-hint">' + F.esc(text || "暂无数据") + "</div>";
  };

  F.kv = function (label, value) {
    return '<div class="side-kv"><span>' + F.esc(label) + "</span><b>" + value + "</b></div>";
  };

  F.progress = function (v, cls) {
    var p = Math.max(0, Math.min(1, Number(v || 0)));
    return '<div class="pbar ' + (cls || "") + '"><i style="width:' + (p * 100).toFixed(1) + '%"></i></div>';
  };

  /* ---------------------------------------------------------- 驾驶舱 */
  F.register("dashboard", function () {
    var b = F.state.boot;
    if (!b) return;
    var k = b.kpi;
    var html = '<div class="kpi-grid six">' +
      '<div class="kpi"><div class="k-label">今日入库</div><div class="k-value">' + F.qty(k.inboundToday) +
      '</div><div class="k-sub">待收货 ' + k.waitReceive + " 单 · 在途 " + k.asnOpen + "</div></div>" +
      '<div class="kpi green"><div class="k-label">今日出库</div><div class="k-value">' +
      F.qty(k.outboundToday) + '</div><div class="k-sub">待发运 ' + k.shipPending + " 单 · 待拣 " +
      k.pickPending + " 行</div></div>" +
      '<div class="kpi"><div class="k-label">在库数量</div><div class="k-value">' + F.wan(k.stockQty) +
      '</div><div class="k-sub">SKU ' + k.skuCount + " 个 · 货位 " + k.locBusy + "/" + k.locTotal +
      "</div></div>" +
      '<div class="kpi green"><div class="k-label">库存货值</div><div class="k-value">' +
      F.wan(k.stockValue) + '</div><div class="k-sub">周转 ' + F.num(k.turnover, 2) +
      " 次/月</div></div>" +
      '<div class="kpi gold"><div class="k-label">库容利用率</div><div class="k-value">' +
      F.pct(k.locUtil, 1) + '</div><div class="k-sub">货位占用 ' + F.pct(k.locOccupied, 0) +
      " · 体积口径</div></div>" +
      '<div class="kpi red"><div class="k-label">临期 / 异常</div><div class="k-value">' +
      k.expiryWarn + " / " + k.excOpen + '</div><div class="k-sub">盘点准确率 ' +
      F.pct(k.accuracy, 1) + " · 准时发运 " + F.pct(k.onTimeRate, 1) + "</div></div></div>";

    html += '<div class="panel"><div class="panel-title">近 14 天出入库作业量' +
      '<span class="panel-actions small muted">单位：件</span></div><div class="panel-body">' +
      F.lineChart([
        { name: "入库", data: (b.trend || []).map(function (t) { return t.inbound; }) },
        { name: "出库", data: (b.trend || []).map(function (t) { return t.outbound; }) },
        { name: "订单数", data: (b.trend || []).map(function (t) { return t.orders; }) }
      ], { labels: (b.trend || []).map(function (t) { return t.day; }),
        colors: ["#1f7a8c", "#c8963e", "#7a5ea8"] }) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">库区负荷' +
      '<span class="panel-actions"><a class="btn sm" href="#locations">库位管理</a></span></div>' +
      '<div class="panel-body flush">' +
      F.table([
        { label: "库区", render: function (r) { return '<b>' + F.esc(r.code) + "</b> " +
          '<span class="small">' + F.esc(r.name) + "</span>"; } },
        { label: "类型", render: function (r) { return F.tag(r.kind, r.kind === "拣货区" ? "blue" :
          (r.kind === "存储区" ? "gray" : "gold")) + (r.pickface ?
          ' <span class="muted small">拣货面</span>' : ""); } },
        { label: "货位", num: true, render: function (r) { return r.locCount + " 个"; } },
        { label: "库存", num: true, render: function (r) { return F.qty(r.stockQty) + " 件"; } },
        { label: "库容", render: function (r) {
          return '<div class="util-cell">' + F.progress(r.util) +
            '<span class="small">' + F.pct(r.util, 0) + "</span></div>";
        } },
        { label: "体积", num: true, render: function (r) {
          return F.cube(r.used) + " / " + F.cube(r.capacity);
        } }
      ], (b.zones || []).slice().sort(function (x, y) { return y.stockQty - x.stockQty; })) +
      "</div></div>";

    var soDist = (b.statusDist || []).filter(function (x) { return x.kind === "出库"; })
      .sort(function (x, y) { return y.count - x.count; });
    html += '<div class="panel"><div class="panel-title">出库单状态分布' +
      '<span class="panel-actions small muted">共 ' + soDist.reduce(function (a, x) {
        return a + x.count;
      }, 0) + " 单</span></div><div class=\"panel-body\">" + F.stageBars(soDist) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">待办与预警' +
      '<span class="panel-actions"><a class="btn sm" href="#reports">看报表</a></span></div>' +
      '<div class="panel-body flush">' +
      F.table([
        { label: "类别", render: function (r) { return F.tag(r.type, "gray"); } },
        { label: "单据", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "事项", render: function (r) { return F.esc(r.title); } },
        { label: "级别", render: function (r) {
          return F.tag(r.level === "high" ? "高" : (r.level === "mid" ? "中" : "低"),
            r.level === "high" ? "red" : (r.level === "mid" ? "gold" : "gray"));
        } },
        { label: "", render: function (r) {
          return '<a class="btn sm" href="#' + F.esc(r.page) + '">处理</a>';
        } }
      ], b.todo || [], { empty: "没有待办，节奏不错" }) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">仓储异常' +
      '<span class="panel-actions small muted">未关闭 ' + (b.exceptions || []).length + " 条</span></div>" +
      '<div class="panel-body flush">' +
      F.table([
        { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "类型", render: function (r) { return F.tag(r.type, "blue"); } },
        { label: "关联单据", render: function (r) { return F.esc(r.refNo || "—"); } },
        { label: "级别", render: function (r) { return F.tag(r.level, r.level === "高" ? "red" : "gold"); } },
        { label: "描述", render: function (r) { return '<span class="small">' + F.esc(r.detail) + "</span>"; } },
        { label: "状态", render: function (r) { return F.tag(r.status); } }
      ], b.exceptions || [], { empty: "无未关闭异常" }) + "</div></div>";

    document.getElementById("view").innerHTML = html;

    F.setSide(
      '<div class="side-block"><div class="hd">今日快照</div><div class="bd">' +
      F.kv("入库量", '<span class="up">' + F.qty(k.inboundToday) + " 件</span>") +
      F.kv("出库量", '<span class="up">' + F.qty(k.outboundToday) + " 件</span>") +
      F.kv("待拣任务", k.pickPending + " 行") +
      F.kv("待发运", k.shipPending + " 单") +
      F.kv("盘点准确率", F.pct(k.accuracy, 1)) +
      "</div></div>" +
      '<div class="side-block"><div class="hd">库存健康</div><div class="bd">' +
      F.kv("临期批次", k.expiryWarn + " 个") +
      F.kv("异常未关闭", k.excOpen + " 条") +
      F.kv("周转（月）", F.num(k.turnover, 2) + " 次") +
      F.kv("货位占用", k.locBusy + "/" + k.locTotal) +
      F.kv("库容利用率", F.pct(k.locUtil, 1)) +
      "</div></div>" +
      '<div class="side-block"><div class="hd">作业规则</div><div class="bd small muted" style="line-height:1.9">' +
      (b.rules || []).slice(0, 8).map(function (r) {
        return "● " + F.esc(r.name) + "：" + r.value + F.esc(r.unit || "");
      }).join("<br>") + "</div></div>");
    F.setStatus("仓储驾驶舱 · 数据截至 " + new Date().toLocaleTimeString("zh-CN"));
  });

  /* ---------------------------------------------------------- 基础设置 */
  F.register("settings", function () {
    var tab = F.state.params.tab || "rules";
    F.api("GET", "/api/settings").then(function (d) {
      var admin = F.isAdmin();
      var html = '<div class="panel"><div class="panel-title">' +
        F.chips([["warehouse", "仓库与库区"], ["rules", "业务规则"],
          ["users", "账号与权限"], ["about", "系统信息"]], tab, "data-tab") +
        "</div><div class='panel-body' id='setBody'></div></div>";
      document.getElementById("view").innerHTML = html;

      var body = document.getElementById("setBody");
      function paint(t) {
        if (t === "warehouse") {
          body.innerHTML = "<div class='sub-title'>仓库</div>" +
            F.table([
              { label: "编码", render: function (r) { return '<span class="mono">' + F.esc(r.code) + "</span>"; } },
              { label: "名称", key: "name" }, { label: "城市", key: "city" },
              { label: "面积（㎡）", num: true, render: function (r) { return F.num(r.area, 0); } },
              { label: "负责人", key: "manager" },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], d.warehouses) +
            "<div class='sub-title'>库区与库容</div>" +
            F.table([
              { label: "库区", render: function (r) { return '<b>' + F.esc(r.code) + "</b> " + F.esc(r.name); } },
              { label: "类型", render: function (r) { return F.tag(r.kind, "gray"); } },
              { label: "温层", key: "temp" },
              { label: "货位", num: true, render: function (r) { return r.locCount; } },
              { label: "库存", num: true, render: function (r) { return F.qty(r.stockQty); } },
              { label: "利用率", render: function (r) {
                return '<div class="util-cell">' + F.progress(r.util) +
                  '<span class="small">' + F.pct(r.util, 0) + "</span></div>";
              } }
            ], d.zones);
        } else if (t === "rules") {
          var cats = {};
          (d.rules || []).forEach(function (r) { (cats[r.category] = cats[r.category] || []).push(r); });
          body.innerHTML = Object.keys(cats).map(function (c) {
            return '<div class="sub-title">' + F.esc(c) + "</div>" + F.table([
              { label: "规则", render: function (r) { return F.esc(r.name) +
                ' <span class="muted small mono">' + F.esc(r.code) + "</span>"; } },
              { label: "当前值", num: true, render: function (r) {
                return '<input class="inp sm" data-rule="' + F.esc(r.code) + '" value="' +
                  r.value + '" style="width:90px"> <span class="muted small">' + F.esc(r.unit) + "</span>";
              } },
              { label: "说明", render: function (r) { return '<span class="small muted">' +
                F.esc(r.remark) + "</span>"; } },
              { label: "状态", render: function (r) { return F.tag(r.enabled ? "启用" : "停用"); } }
            ], cats[c]);
          }).join("") + (admin ? '<div class="form-foot"><button class="btn primary" id="ruleSave">' +
            "保存规则</button></div>" : '<div class="muted small">仅管理员可修改规则</div>');
          var sv = document.getElementById("ruleSave");
          if (sv) sv.addEventListener("click", function () {
            var list = [];
            body.querySelectorAll("[data-rule]").forEach(function (i) {
              list.push([i.getAttribute("data-rule"), i.value]);
            });
            var seq = Promise.resolve();
            list.forEach(function (x) {
              seq = seq.then(function () {
                return F.api("PUT", "/api/rules/" + x[0], { value: Number(x[1]) });
              });
            });
            seq.then(function () {
              F.toast("规则已保存", "ok");
              F.boot();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        } else if (t === "users") {
          body.innerHTML = (admin ? '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn primary" id="uNew">新建账号</button></div>' : "") +
            F.table([
              { label: "账号", render: function (r) { return '<span class="mono">' + F.esc(r.username) + "</span>"; } },
              { label: "姓名", key: "displayName" },
              { label: "角色", render: function (r) { return F.tag(r.roleLabel, "blue"); } },
              { label: "部门", key: "dept" }, { label: "手机", key: "phone" },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], d.users) +
            "<div class='sub-title'>角色权限矩阵</div>" +
            F.table([{ label: "角色", render: function (r) { return F.esc(r.label) +
              ' <span class="muted small mono">' + F.esc(r.role) + "</span>"; } },
              { label: "权限", render: function (r) {
                return (r.perms || []).map(function (p) {
                  return '<span class="tag gray">' + F.esc(d.permLabel[p] || p) + "</span>";
                }).join(" ");
              } }], d.roles);
          var nb = document.getElementById("uNew");
          if (nb) nb.addEventListener("click", function () {
            F.dialog("新建账号",
              '<div class="form-grid">' +
              '<label>账号<input id="nuName" placeholder="小写字母/数字"></label>' +
              '<label>姓名<input id="nuDisplay"></label>' +
              '<label>角色<select id="nuRole">' + (d.roles || []).map(function (r) {
                return '<option value="' + F.esc(r.role) + '">' + F.esc(r.label) + "</option>";
              }).join("") + "</select></label>" +
              '<label>部门<input id="nuDept" placeholder="如 仓储部"></label>' +
              '<label>初始密码<input id="nuPwd" value="wh@2026"></label></div>',
              '<button class="btn" id="nuOk">创建</button>');
            document.getElementById("nuOk").addEventListener("click", function () {
              F.api("POST", "/api/users", {
                username: document.getElementById("nuName").value.trim(),
                displayName: document.getElementById("nuDisplay").value.trim(),
                role: document.getElementById("nuRole").value,
                dept: document.getElementById("nuDept").value.trim(),
                password: document.getElementById("nuPwd").value
              }).then(function () {
                F.closeDialog(); F.toast("账号已创建", "ok"); F.go("settings", { tab: "users" });
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
        } else {
          body.innerHTML = '<div class="kv-grid">' +
            F.kv("系统名称", "飞传 WMS · 仓储执行系统") +
            F.kv("版本", d.version) +
            F.kv("接口条目", "GET /api/openapi.json") +
            F.kv("物料数", d.counts.items) +
            F.kv("货位数", d.counts.locations) +
            F.kv("库区数", d.counts.zones) +
            F.kv("批次数", d.counts.lots) +
            F.kv("流水数", d.counts.moves) +
            "</div>" +
            '<div class="sub-title">部署与对接说明</div>' +
            '<div class="panel-body small muted" style="line-height:2">' +
            "· 零第三方依赖：Python 标准库 http.server + SQLite（WAL），单进程即可运行。<br>" +
            "· 前端为原生 HTML/CSS/JS，无构建步骤，hash 路由；同一份静态资源可由任意反向代理托管。<br>" +
            "· 与 ERP / MES / TMS 对接走「三通道」：API Key（fck_ 前缀）、Webhook（HMAC-SHA256 签名）、" +
            "增量同步 /api/sync/changes 游标拉取。<br>" +
            "· 令牌支持 Authorization / X-Fc-Token / Cookie / 查询串多通道携带，避免代理改写导致掉登录。</div>";
        }
      }
      paint(tab);
      document.querySelectorAll("[data-tab]").forEach(function (b) {
        b.addEventListener("click", function () {
          document.querySelectorAll("[data-tab]").forEach(function (x) { x.className = "chip"; });
          b.className = "chip on";
          paint(b.getAttribute("data-tab"));
        });
      });
      F.setStatus("基础设置 · " + (TITLE[F.state.route] || ""));
    }).catch(function (e) { F.toast(e.message, "err"); });
  });

  /* ---------------------------------------------------------- 操作日志 */
  F.register("logs", function () {
    var q = F.state.params.q || "";
    F.api("GET", "/api/logs?limit=200" + (q ? "&q=" + encodeURIComponent(q) : ""))
      .then(function (d) {
        var html = '<div class="panel"><div class="panel-title">操作日志' +
          '<span class="panel-actions">' +
          '<input class="inp sm" id="logQ" placeholder="搜索动作或详情" value="' + F.esc(q) + '">' +
          '<button class="btn sm" id="logGo">查询</button></span></div>' +
          '<div class="panel-body flush">' +
          F.table([
            { label: "时间", render: function (r) { return '<span class="mono small">' +
              F.esc(r.created_at) + "</span>"; } },
            { label: "操作人", render: function (r) { return F.esc(r.username); } },
            { label: "动作", render: function (r) { return F.tag(r.action, "blue"); } },
            { label: "详情", render: function (r) { return '<span class="small">' + F.esc(r.detail) + "</span>"; } }
          ], d.list, { empty: "暂无日志" }) + "</div></div>";
        document.getElementById("view").innerHTML = html;
        document.getElementById("logGo").addEventListener("click", function () {
          F.go("logs", { q: document.getElementById("logQ").value.trim() });
        });
        F.setStatus("操作日志 · 共 " + d.total + " 条");
        F.setSide('<div class="side-block"><div class="hd">说明</div><div class="bd small muted" ' +
          'style="line-height:1.9">所有写操作都会落审计日志：登录、单据创建与状态推进、' +
          '收货上架、分配拣货、发运、盘点调整、集成配置变更等。</div></div>');
      }).catch(function (e) { F.toast(e.message, "err"); });
  });

  /* ---------------------------------------------------------- 启动 */
  F.boot = function () {
    return F.api("GET", "/api/bootstrap").then(function (d) {
      F.state.boot = d;
      var u = d.user;
      var op = document.getElementById("opFoot");
      if (op) op.textContent = "操作员：" + u.displayName + "（" + u.roleLabel + "）";
      var sku = document.getElementById("skuLabel");
      if (sku) sku.textContent = "在库 SKU：" + d.kpi.skuCount;
      var pk = document.getElementById("pickLabel");
      if (pk) pk.textContent = "待拣任务：" + d.kpi.pickPending;
      var ut = document.getElementById("utilLabel");
      if (ut) ut.textContent = "库容：" + F.pct(d.kpi.locUtil, 1);
      return d;
    });
  };

  function start() {
    if (!localStorage.getItem(TOKEN_KEY)) { location.href = "./login.html"; return; }
    F.boot().then(function () {
      render();
      window.addEventListener("hashchange", render);
      var lo = document.getElementById("btnLogout");
      if (lo) lo.addEventListener("click", function () {
        F.api("POST", "/api/auth/logout", {}).then(function () {
          localStorage.removeItem(TOKEN_KEY);
          document.cookie = "wms_token=; path=/; max-age=0";
          location.href = "./login.html";
        }).catch(function () {
          localStorage.removeItem(TOKEN_KEY);
          location.href = "./login.html";
        });
      });
    }).catch(function (e) {
      if (e.status === 401) return;
      document.getElementById("view").innerHTML =
        '<div class="panel"><div class="panel-body">初始化失败：' + F.esc(e.message) + "</div></div>";
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window, document);
