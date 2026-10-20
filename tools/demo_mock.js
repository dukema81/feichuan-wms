/* 飞传 WMS · 离线 DEMO 数据层：拦截 fetch，在浏览器内存中实现与后端同口径的读写 */
(function () {
  "use strict";
  if (!window.__DEMO__ || !window.DB) return;

  var DB = window.DB;

  var STORE_KEY = "fc_wms_demo";
  try {
    var saved = sessionStorage.getItem(STORE_KEY);
    if (saved) {
      var parsed = JSON.parse(saved);
      if (parsed && parsed.asnD && parsed.orderD) DB = window.DB = parsed;
    }
  } catch (e) { /* 隐私模式忽略 */ }

  function persist() {
    try {
      var s = JSON.stringify(DB);
      if (s.length < 4.5e6) sessionStorage.setItem(STORE_KEY, s);
    } catch (e) { /* 超限或隐私模式忽略 */ }
  }

  var NOW = new Date();
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function r2(v) { return Math.round((Number(v || 0) + 1e-9) * 100) / 100; }
  function r4(v) { return Math.round((Number(v || 0) + 1e-9) * 10000) / 10000; }
  function today() {
    return NOW.getFullYear() + "-" + pad(NOW.getMonth() + 1) + "-" + pad(NOW.getDate());
  }
  function nowStr() {
    return today() + " " + pad(NOW.getHours()) + ":" + pad(NOW.getMinutes()) + ":" +
      pad(NOW.getSeconds());
  }
  function addDays(n) {
    var d = new Date(NOW.getTime() + n * 86400000);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function clone(x) { return JSON.parse(JSON.stringify(x)); }
  function find(list, key, val) {
    for (var i = 0; i < (list || []).length; i++) if (list[i][key] === val) return list[i];
    return null;
  }
  function docNo(list, prefix) {
    var max = 0;
    (list || []).forEach(function (x) {
      var m = String(x.no || "").match(/(\d+)$/);
      if (m) max = Math.max(max, Number(m[1]));
    });
    return prefix + today().replace(/-/g, "") + "-" + ("000" + (max + 1)).slice(-4);
  }
  function daysLeft(expiry) {
    if (!expiry) return null;
    var d = new Date(expiry + "T00:00:00"), t = new Date(today() + "T00:00:00");
    return Math.round((d - t) / 86400000);
  }
  function expLevel(expiry) {
    var n = daysLeft(expiry);
    if (n === null) return "正常";
    if (n < 0) return "已过期";
    if (n <= 30) return "临期";
    if (n <= 90) return "关注";
    return "正常";
  }
  function cubeOf(l, w, h, qty) {
    return r4(Number(l || 0) * Number(w || 0) * Number(h || 0) * Number(qty || 1) / 1e6);
  }

  /* 演示环境固定以管理员身份进入 */
  DB.me = { username: "admin", displayName: "系统管理员", role: "admin",
    roleLabel: "系统管理员", authType: "demo",
    perms: ["read", "write", "receive", "putaway", "pick", "pack", "ship", "alloc",
      "count", "adjust", "approve"] };
  DB.boot.user = DB.me;
  DB.__changes = DB.sync.list || [];
  DB.__changeId = DB.__changes.reduce(function (a, c) { return Math.max(a, c.id || 0); }, 0);
  DB.__keySeq = (DB.integ.keys.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__hookSeq = (DB.integ.webhooks.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__dlvSeq = (DB.integ.deliveries.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__mapSeq = (DB.integ.mappings.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__logs = DB.logs.list || [];

  var ASN_FLOW = ["草稿", "已预约", "已到货", "收货中", "已收货", "已上架", "已关闭"];
  var SO_FLOW = ["草稿", "已提交", "已分配", "拣货中", "已拣货", "已复核", "已发运", "已签收"];
  var ST_FLOW = ["草稿", "盘点中", "待审核", "已调整", "已关闭"];

  function idx(flow, s) { return flow.indexOf(s); }

  function log(action, detail) {
    DB.__logs.unshift({ id: (DB.__logs.length ? DB.__logs[0].id : 0) + 1,
      username: DB.me.username, action: action, detail: detail || "",
      ip: "127.0.0.1", created_at: nowStr() });
    if (DB.__logs.length > 300) DB.__logs.pop();
    DB.__changeId += 1;
    DB.__changes.push({ id: DB.__changeId, object: "op", object_id: String(detail || ""),
      action: action, actor: DB.me.username, payload: "{}", changed_at: nowStr() });
    DB.integ.overview.changes = DB.__changes.length;
    DB.integ.overview.lastChange = nowStr();
  }

  /* ------------------------------------------------------------ 库存口径 */
  function itemOf(code) { return DB.itemD[code] || {}; }

  function stockRows() { return DB.stock.list; }

  function findStock(item, lot, loc) {
    return stockRows().filter(function (s) {
      return s.item === item && s.lot === lot && s.location === loc;
    })[0] || null;
  }

  function addStock(item, lot, loc, qty, price, expiry) {
    var s = findStock(item, lot, loc);
    if (s) {
      s.qty = r2(s.qty + qty);
    } else {
      s = { id: -Math.floor(Math.random() * 1e9), whCode: "WH-SZ01", item: item,
        name: itemOf(item).name || "", abc: itemOf(item).abc || "",
        category: itemOf(item).category || "", unit: itemOf(item).unit || "",
        lot: lot, location: loc, qty: r2(qty), allocated: 0, frozen: 0, price: r2(price || 0),
        amount: r2(qty * (price || 0)), expiry: expiry || "", daysLeft: daysLeft(expiry),
        expiryLevel: expLevel(expiry), inboundAt: nowStr(), ageDays: 0, status: "正常" };
      stockRows().unshift(s);
    }
    s.avail = r2(s.qty - s.allocated - s.frozen);
    s.amount = r2(s.qty * s.price);
    var lotRow = (DB.lots.list || []).filter(function (x) { return x.lot === lot; })[0];
    if (lotRow) lotRow.qty = r2(Number(lotRow.qty || 0) + qty);
    var locRow = find(DB.locations.list, "code", loc);
    if (locRow) {
      locRow.used = r2(Number(locRow.used || 0) + cubeOf(itemOf(item).length,
        itemOf(item).width, itemOf(item).height, qty));
      locRow.util = r4(locRow.capacity ? locRow.used / locRow.capacity : 0);
      locRow.stockQty = r2(Number(locRow.stockQty || 0) + qty);
      locRow.skuCount = (locRow.skuCount || 0) + (s.qty === qty ? 1 : 0);
    }
    return s;
  }

  function takeStock(item, lot, loc, qty) {
    var s = findStock(item, lot, loc);
    if (!s) return false;
    s.qty = r2(Math.max(0, s.qty - qty));
    s.allocated = r2(Math.max(0, s.allocated - qty));
    s.avail = r2(s.qty - s.allocated - s.frozen);
    var locRow = find(DB.locations.list, "code", loc);
    if (locRow) {
      locRow.used = r2(Math.max(0, Number(locRow.used || 0) -
        cubeOf(itemOf(item).length, itemOf(item).width, itemOf(item).height, qty)));
      locRow.util = r4(locRow.capacity ? locRow.used / locRow.capacity : 0);
    }
    return true;
  }

  function addMove(type, item, lot, from, to, qty, refNo, note) {
    DB.moves.list.unshift({ id: -Math.floor(Math.random() * 1e9), no: docNo([], "MV") +
      "-" + Math.floor(Math.random() * 90 + 10), ts: nowStr(), type: type, item: item,
      lot: lot, from_loc: from || "", to_loc: to || "", qty: r2(qty), ref_no: refNo || "",
      operator: DB.me.username, note: note || "" });
    if (DB.moves.total !== undefined) DB.moves.total += 1;
    DB.moves.list = DB.moves.list.slice(0, 800);
  }

  /* ------------------------------------------------------------ 门禁口径 */
  function asnCtx(a) {
    var items = a.items || [], tot = 0, recv = 0, diffOpen = 0;
    items.forEach(function (x) {
      tot += Number(x.qty || 0); recv += Number(x.receivedQty || 0);
      if (Number(x.receivedQty || 0) < Number(x.qty || 0) * 0.98 && !x.diffReason) diffOpen += 1;
    });
    var qcDone = items.length > 0 && items.every(function (x) {
      return Number(x.receivedQty || 0) <= 0 || x.qcStatus !== "待检";
    });
    var qcOk = qcDone && !items.some(function (x) { return x.qcStatus === "不合格"; });
    var tasks = a.tasks || [];
    var putawayDone = tasks.length > 0 && tasks.every(function (t) { return t.status === "已完成"; });
    var posted = (a.moves || []).some(function (m) { return m.type === "上架"; });
    var sup = find(DB.suppliers.list, "code", a.supplier);
    return { status: a.status, items: items.length, qty: r2(tot), received: r2(recv),
      receivedRate: r4(tot ? recv / tot : 0), supplierOk: !!(sup && sup.status === "启用"),
      expectDate: a.expectDate, arriveDate: a.arriveAt, diffOpen: diffOpen,
      qcDone: qcDone, qcOk: qcOk, putawayDone: putawayDone, stockPosted: posted,
      taskCount: tasks.length };
  }

  function gateList(flow, target, miss, cur) {
    return flow.filter(function (t) {
      return idx(flow, t) > idx(flow, cur);
    }).map(function (t) {
      var m = t === target ? miss : gateMiss(flow, t, cur);
      return { target: t, ok: !(m && m.length), missing: m || [],
        next: t === flow[idx(flow, cur) + 1], cancel: false };
    });
    function gateMiss(f, t, c) {
      if (f === ASN_FLOW) return asnGateMiss(t, asnCtx(cur.__asn));
      if (f === SO_FLOW) return soGateMiss(t, soCtx(cur.__order));
      return stGateMiss(t, stCtx(cur.__st));
    }
  }

  function asnGate(target, a) {
    var ctx = asnCtx(a), miss = [];
    if (target === "已预约") {
      if (!ctx.supplierOk) miss.push("供应商未启用或不存在");
      if (ctx.items <= 0) miss.push("到货通知没有明细行");
      if (!ctx.expectDate) miss.push("未填写预约到货日期");
    } else if (target === "已到货") {
      if (!ctx.arriveDate) miss.push("未登记实际到货时间");
      if (ctx.status !== "已预约") miss.push("单据未处于已预约状态");
    } else if (target === "已收货") {
      if (ctx.receivedRate < 1 - 1e-9) {
        miss.push("收货完成度 " + Math.round(ctx.receivedRate * 100) + "%，未收齐");
      }
      if (ctx.diffOpen > 0) miss.push("存在 " + ctx.diffOpen + " 行未处置的收货差异");
    } else if (target === "已上架") {
      if (!ctx.qcDone) miss.push("来料质检未完成");
      if (!ctx.qcOk) miss.push("来料质检未判定合格（可让步接收后再上架）");
      if (!ctx.putawayDone) miss.push("上架任务未全部完成");
    } else if (target === "已关闭") {
      if (!ctx.stockPosted) miss.push("库存尚未正式入账");
    }
    return { miss: miss, ctx: ctx };
  }

  function asnGateView(a) {
    var out = [], nxt = ASN_FLOW[idx(ASN_FLOW, a.status) + 1] || null;
    ASN_FLOW.forEach(function (t) {
      if (idx(ASN_FLOW, t) <= idx(ASN_FLOW, a.status)) return;
      var g = asnGate(t, a);
      out.push({ target: t, ok: !g.miss.length, missing: g.miss,
        next: t === nxt, cancel: false });
    });
    return { ctx: asnCtx(a), gates: out, next: nxt,
      cancelable: ["已上架", "已关闭", "已取消"].indexOf(a.status) < 0 };
  }

  function soCtx(o) {
    var items = o.items || [];
    var pickedAll = items.length > 0 && items.every(function (x) {
      return Number(x.pickedQty || 0) >= Number(x.qty || 0) - 1e-9;
    });
    var packs = o.packages ? [o.packages] : (o.packageNo ? [1] : []);
    var cr = find(DB.carriers.list, "code", o.carrier);
    return { status: o.status, items: items.length,
      customerOk: !!(find(DB.customers.list, "code", o.customer) || {}).code,
      fillRate: Number(o.fillRate || 0),
      allocDone: Number(o.allocatedQty || 0) > 0,
      waveNo: o.waveNo || "", pickedAll: pickedAll,
      packCount: o.packages ? 1 : 0, checkDiff: 0,
      carrierOk: !!(cr && cr.status === "启用"),
      trackingNo: o.trackingNo || "", signedAt: o.signedAt || "" };
  }

  function soGate(target, o) {
    var ctx = soCtx(o), miss = [];
    if (target === "已提交") {
      if (ctx.items <= 0) miss.push("出库单没有明细行");
      if (!ctx.customerOk) miss.push("客户被冻结或不存在");
    } else if (target === "已发运") {
      if (!ctx.carrierOk) miss.push("承运商未启用或不存在");
      if (!ctx.trackingNo) miss.push("尚未生成运单号");
    } else if (target === "已签收") {
      if (!ctx.signedAt) miss.push("未登记签收时间");
    }
    return { miss: miss, ctx: ctx };
  }

  function soGateView(o) {
    var out = [], nxt = SO_FLOW[idx(SO_FLOW, o.status) + 1] || null;
    ["已提交", "已发运", "已签收"].forEach(function (t) {
      if (idx(SO_FLOW, t) <= idx(SO_FLOW, o.status)) return;
      var g = soGate(t, o);
      out.push({ target: t, ok: !g.miss.length, missing: g.miss, next: t === nxt, cancel: false });
    });
    return { ctx: soCtx(o), gates: out, next: nxt,
      cancelable: ["拣货中", "已拣货", "已复核", "已发运", "已签收", "已取消"].indexOf(o.status) < 0 };
  }

  function stCtx(t) {
    var items = t.items || [];
    var countedAll = items.length > 0 && items.every(function (x) { return x.status === "已盘"; });
    var diffLines = items.filter(function (x) {
      return Math.abs(Number(x.diffQty || 0)) > 1e-9;
    }).length;
    return { status: t.status, items: items.length, countedAll: countedAll,
      diffLines: diffLines, adjusted: diffLines === 0 || t.adjusted,
      approveBy: t.approveBy || "" };
  }

  function stGateView(t) {
    var ctx = stCtx(t), out = [];
    ["待审核", "已调整", "已关闭"].forEach(function (tg) {
      if (idx(ST_FLOW, tg) <= idx(ST_FLOW, t.status)) return;
      var miss = [];
      if (tg === "待审核" && !ctx.countedAll) miss.push("仍有货位未录入实盘数");
      if (tg === "已调整") {
        if (!ctx.approveBy && tg !== "已调整") miss.push("未经审核人放行");
        if (ctx.diffLines > 0 && !ctx.adjusted) miss.push("存在差异行但未生成库存调整");
      }
      if (tg === "已关闭" && ctx.status !== "已调整") miss.push("盘点单未完成调整");
      out.push({ target: tg, ok: !miss.length, missing: miss,
        next: tg === ST_FLOW[idx(ST_FLOW, t.status) + 1], cancel: false });
    });
    return { ctx: ctx, gates: out };
  }

  function refreshAsn(a) {
    var tot = 0, recv = 0;
    (a.items || []).forEach(function (x) {
      tot += Number(x.qty || 0); recv += Number(x.receivedQty || 0);
    });
    a.qty = r2(tot); a.receivedQty = r2(recv);
    a.receivedRate = r4(tot ? recv / tot : 0);
    a.lineCount = (a.items || []).length;
    a.gate = asnGateView(a);
    var row = find(DB.asns.list, "no", a.no);
    if (row) { row.status = a.status; row.receivedRate = a.receivedRate; }
  }

  function refreshOrder(o) {
    var tot = 0, alloc = 0, picked = 0;
    (o.items || []).forEach(function (x) {
      tot += Number(x.qty || 0); alloc += Number(x.allocatedQty || 0);
      picked += Number(x.pickedQty || 0);
    });
    o.qty = r2(tot); o.allocatedQty = r2(alloc); o.pickedQty = r2(picked);
    o.lineCount = (o.items || []).length;
    o.progress = r4(tot ? picked / tot : 0);
    o.gate = soGateView(o);
    var row = find(DB.orders.list, "no", o.no);
    if (row) { row.status = o.status; row.fillRate = o.fillRate; row.progress = o.progress; }
  }

  function refreshSt(t) {
    t.lineCount = (t.items || []).length;
    t.diffCount = (t.items || []).filter(function (x) {
      return Math.abs(Number(x.diffQty || 0)) > 1e-9;
    }).length;
    t.countedAll = t.items.length > 0 && t.items.every(function (x) { return x.status === "已盘"; });
    t.gate = stGateView(t);
    var row = find(DB.stocktakes.list, "no", t.no);
    if (row) { row.status = t.status; row.diffLines = t.diffLines; }
  }

  function refreshBoot() {
    var k = DB.boot.kpi, inbound = 0, outbound = 0, stockQty = 0, stockValue = 0;
    DB.moves.list.forEach(function (m) {
      if (m.ts.indexOf(today()) === 0) {
        if (m.type === "上架" || m.type === "收货") inbound += Number(m.qty || 0);
        if (m.type === "拣货出库") outbound += Number(m.qty || 0);
      }
    });
    stockRows().forEach(function (s) { stockQty += Number(s.qty || 0); stockValue += Number(s.amount || 0); });
    k.inboundToday = r2(inbound); k.outboundToday = r2(outbound);
    k.stockQty = r2(stockQty); k.stockValue = r2(stockValue / 10000.0);
    k.asnOpen = DB.asns.list.filter(function (x) {
      return ["已预约", "已到货", "收货中", "已收货"].indexOf(x.status) >= 0;
    }).length;
    k.soOpen = DB.orders.list.filter(function (x) {
      return ["已提交", "已分配", "拣货中", "已拣货", "已复核"].indexOf(x.status) >= 0;
    }).length;
    k.pickPending = DB.putaway ? 0 : k.pickPending;
    var busy = (DB.locations.list || []).filter(function (x) { return Number(x.used || 0) > 0; }).length;
    k.locBusy = busy; k.locTotal = (DB.locations.list || []).length;
    k.locUtil = r4(stockRows().length ?
      DB.locations.list.reduce(function (a, x) { return a + Number(x.util || 0); }, 0) /
      Math.max(1, (DB.locations.list || []).length) : 0);
  }

  /* ------------------------------------------------------------ 通用应答 */
  function ok(data) { return { status: 200, body: { ok: true, data: data } }; }
  function bad(msg, code) { return { status: code || 400, body: { ok: false, error: msg } }; }
  function need(list, kw) {
    if (!kw.q) return list;
    var q = String(kw.q).toLowerCase();
    return list.filter(function (x) {
      return JSON.stringify(x).toLowerCase().indexOf(q) >= 0;
    });
  }
  function kwOf(qs) { return qs; }

  /* ------------------------------------------------------------ 路由表 */
  var ROUTES = [];
  function on(method, re, fn) { ROUTES.push([method, re, fn]); }

  /* ---- 认证 ---- */
  on("GET", /^api\/auth\/me$/, function () { return ok(DB.me); });
  on("POST", /^api\/auth\/logout$/, function () { return ok({ logout: true }); });
  on("POST", /^api\/auth\/password$/, function () { return ok({ changed: true }); });
  on("GET", /^api\/bootstrap$/, function () { refreshBoot(); return ok(DB.boot); });

  /* ---- 主数据 ---- */
  on("GET", /^api\/warehouses$/, function () { return ok({ list: DB.warehouses.list, total: DB.warehouses.list.length }); });
  on("GET", /^api\/zones$/, function () { return ok({ list: DB.zones.list, total: DB.zones.list.length }); });
  on("GET", /^api\/locations$/, function (m, qs) {
    var list = DB.locations.list;
    if (qs.zone && qs.zone !== "全部") {
      list = list.filter(function (x) { return x.zone === qs.zone; });
    }
    if (qs.location) list = list.filter(function (x) { return x.code === qs.location; });
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/items$/, function (m, qs) {
    var list = DB.items.list;
    if (qs.abc && qs.abc !== "全部") list = list.filter(function (x) { return x.abc === qs.abc; });
    if (qs.category && qs.category !== "全部") {
      list = list.filter(function (x) { return x.category === qs.category; });
    }
    if (qs.q) list = need(list, qs);
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/items\/([A-Za-z0-9\-_]+)$/, function (m) {
    var d = DB.itemD[m[1]];
    return d ? ok(d) : bad("物料不存在：" + m[1], 404);
  });
  on("POST", /^api\/items$/, function (m, qs, b) {
    if (!b.code || !b.name) return bad("物料编码与名称不能为空");
    if (find(DB.items.list, "code", b.code)) return bad("物料编码已存在：" + b.code);
    var rec = { code: b.code, name: b.name, spec: b.spec || "", category: b.category || "其他",
      unit: b.unit || "件", abc: b.abc || "C", barcode: "", packQty: 0,
      length: Number(b.length || 0), width: Number(b.width || 0), height: Number(b.height || 0),
      weight: Number(b.weight || 0), cube: cubeOf(b.length, b.width, b.height),
      price: Number(b.price || 0), safety: Number(b.safetyStock || b.safety || 0),
      reorder: Number(b.reorder || 0), shelfLife: Number(b.shelfLife || 0),
      storage: b.storage || "常温", status: "启用", stockQty: 0, locCount: 0,
      level: "断货" };
    DB.items.list.unshift(rec);
    DB.itemD[b.code] = clone(rec);
    DB.itemD[b.code].stocks = []; DB.itemD[b.code].recentMoves = [];
    DB.itemD[b.code].recentOrders = []; DB.itemD[b.code].pickface = [];
    log("新建物料", b.code);
    return ok({ code: b.code, created: true });
  });
  on("PUT", /^api\/items\/([A-Za-z0-9\-_]+)$/, function (m, qs, b) {
    var it = find(DB.items.list, "code", m[1]);
    if (!it) return bad("物料不存在", 404);
    ["name", "spec", "category", "unit", "price", "safety", "safetyStock", "reorder",
      "shelfLife", "storage", "status", "abc"].forEach(function (k) {
      if (b[k] !== undefined) it[k] = b[k];
    });
    log("修改物料", m[1]);
    return ok({ code: m[1], updated: true });
  });
  [["suppliers"], ["customers"], ["carriers"]].forEach(function (pair) {
    var key = pair[0];
    on("GET", new RegExp("^api\\/" + key + "$"), function () {
      var list = DB[key].list;
      return ok({ list: list, total: list.length });
    });
    on("POST", new RegExp("^api\\/" + key + "$"), function (m, qs, b) {
      var prefix = key === "suppliers" ? "SUP" : (key === "customers" ? "CUS" : "CR");
      var code = b.code || prefix + "-" + ("00" + (DB[key].list.length + 1)).slice(-2);
      if (find(DB[key].list, "code", code)) return bad("编码已存在：" + code);
      var rec = clone(b);
      rec.code = code;
      rec.status = b.status || "启用";
      if (key === "customers") rec.level = b.level || "普通";
      if (key === "carriers") { rec.cutoff = b.cutoff || "18:00"; rec.onTime = 1.0; }
      DB[key].list.unshift(rec);
      log("新建往来单位", code);
      return ok({ code: code, created: true });
    });
  });

  /* ---- 入库 ---- */
  on("GET", /^api\/asns$/, function (m, qs) {
    var list = DB.asns.list;
    if (qs.status && qs.status !== "全部") {
      list = list.filter(function (x) { return x.status === qs.status; });
    }
    if (qs.q) list = need(list, qs);
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/asns\/([A-Za-z0-9\-]+)$/, function (m) {
    var d = DB.asnD[m[1]];
    return d ? ok(d) : bad("到货通知不存在：" + m[1], 404);
  });
  on("POST", /^api\/asns$/, function (m, qs, b) {
    if (!b.supplier || !find(DB.suppliers.list, "code", b.supplier)) {
      return bad("请选择启用的供应商");
    }
    if (!b.items || !b.items.length) return bad("到货通知至少需要一行明细");
    var no = docNo(DB.asns.list, "ASN");
    var sup = find(DB.suppliers.list, "code", b.supplier);
    var a = { no: no, supplier: b.supplier, supplierName: sup ? sup.name : "",
      whCode: "WH-SZ01", poNo: b.poNo || "", expectDate: b.expectDate || addDays(1),
      arriveAt: "", status: "草稿", priority: b.priority || "普通", dock: b.dock || "",
      note: b.note || "", createdBy: DB.me.username, createdAt: nowStr(), closedAt: "",
      lineCount: 0, qty: 0, receivedQty: 0, receivedRate: 0, cold: false, items: [],
      tasks: [], moves: [], gate: null };
    b.items.forEach(function (it, i) {
      var im = itemOf(it.item);
      if (!im.code) return bad("物料不存在：" + it.item);
      a.items.push({ line: i + 1, item: it.item, name: im.name || "", qty: Number(it.qty || 0),
        receivedQty: 0, lot: it.lot || ("LOT" + today().replace(/-/g, "") + "-" +
          ("00" + (i + 1)).slice(-2)),
        expiry: it.expiry || (im.shelfLife ? addDays(im.shelfLife) : ""),
        price: Number(it.price !== undefined ? it.price : im.price || 0),
        qcStatus: "待检", qcQty: 0, diffReason: "" });
    });
    DB.asnD[no] = a;
    DB.asns.list.unshift({ no: no, supplier: b.supplier, supplierName: sup ? sup.name : "",
      poNo: b.poNo || "", expectDate: a.expectDate, status: "草稿",
      priority: a.priority, lineCount: a.items.length, qty: 0, receivedQty: 0,
      receivedRate: 0, createdAt: nowStr() });
    refreshAsn(a);
    log("新建到货通知", no);
    return ok({ no: no, lines: a.items.length });
  });
  on("POST", /^api\/asns\/([A-Za-z0-9\-]+)\/stage$/, function (m, qs, b) {
    var a = DB.asnD[m[1]];
    if (!a) return bad("到货通知不存在", 404);
    var target = b.target;
    if (ASN_FLOW.indexOf(target) < 0) return bad("目标状态不合法：" + target);
    if (target === "已到货" && !a.arriveAt) a.arriveAt = nowStr();
    if (idx(ASN_FLOW, target) <= idx(ASN_FLOW, a.status)) {
      return bad("不允许从「" + a.status + "」推进到「" + target + "」");
    }
    var g = asnGate(target, a);
    if (g.miss.length) return bad("「" + target + "」闸口未通过：" + g.miss.join("；"));
    a.status = target;
    if (target === "已关闭") a.closedAt = nowStr();
    refreshAsn(a);
    log("推进到货通知", m[1] + " → " + target);
    return ok({ no: a.no, status: target });
  });
  on("POST", /^api\/asns\/([A-Za-z0-9\-]+)\/receive$/, function (m, qs, b) {
    var a = DB.asnD[m[1]];
    if (!a) return bad("到货通知不存在", 404);
    if (["已上架", "已关闭", "已取消"].indexOf(a.status) >= 0) {
      return bad("单据已终结，不能收货");
    }
    if (["草稿", "已预约"].indexOf(a.status) >= 0) { a.status = "已到货"; a.arriveAt = a.arriveAt || nowStr(); }
    var lines = b.items || [{ line: b.line, qty: b.qty }];
    var done = [];
    for (var i = 0; i < lines.length; i++) {
      var row = (a.items || []).filter(function (x) { return x.line === Number(lines[i].line); })[0];
      if (!row) return bad("明细行不存在：第 " + lines[i].line + " 行");
      var q = Number(lines[i].qty || 0);
      if (q <= 0) return bad("收货数量必须大于 0");
      if (Number(row.receivedQty || 0) + q > Number(row.qty) * 1.05 + 1e-9) {
        return bad("第 " + row.line + " 行超收：计划 " + row.qty + "，容差 5%");
      }
      row.receivedQty = r2(Number(row.receivedQty || 0) + q);
      if (lines[i].lot) row.lot = lines[i].lot;
      done.push({ line: row.line, received: row.receivedQty });
    }
    if (a.status === "已到货") a.status = "收货中";
    a.moves = a.moves || [];
    done.forEach(function (x) {
      var row2 = a.items.filter(function (y) { return y.line === x.line; })[0];
      a.moves.push({ no: "", ts: nowStr(), type: "收货", item: row2.item, lot: row2.lot,
        from_loc: "月台", to_loc: "F-01-01-1", qty: row2.receivedQty, ref_no: a.no,
        operator: DB.me.username, note: "到货收货" });
    });
    refreshAsn(a);
    log("ASN 收货", m[1] + " 收货 " + done.length + " 行");
    return ok({ no: a.no, lines: done, ctx: asnCtx(a) });
  });
  on("POST", /^api\/asns\/([A-Za-z0-9\-]+)\/qc$/, function (m, qs, b) {
    var a = DB.asnD[m[1]];
    if (!a) return bad("到货通知不存在", 404);
    var result = b.result;
    if (["合格", "不合格", "让步接收"].indexOf(result) < 0) {
      return bad("质检结论只能是 合格 / 不合格 / 让步接收");
    }
    var n = 0;
    (a.items || []).forEach(function (x) {
      if (Number(x.receivedQty || 0) > 0) { x.qcStatus = result; n += 1; }
    });
    if (!n) return bad("没有可检的收货明细");
    refreshAsn(a);
    log("来料质检", m[1] + " " + result);
    return ok({ no: a.no, done: n });
  });
  on("POST", /^api\/asns\/([A-Za-z0-9\-]+)\/putaway$/, function (m) {
    var a = DB.asnD[m[1]];
    if (!a) return bad("到货通知不存在", 404);
    var ctx = asnCtx(a);
    if (!ctx.qcDone) return bad("来料质检未完成，不能上架");
    if (!ctx.qcOk) return bad("来料质检未判定合格（或让步接收），不能上架");
    if (a.tasks && a.tasks.length) {
      return ok({ no: a.no, created: 0, tasks: a.tasks, note: "上架任务已存在" });
    }
    a.tasks = [];
    (a.items || []).forEach(function (x) {
      if (Number(x.receivedQty || 0) <= 0) return;
      var im = itemOf(x.item);
      var cold = (im.storage || "常温") in { "冷藏": 1, "冷冻": 1 };
      var zone = cold ? "C" : (im.abc === "A" ? "B" : "A");
      var cand = DB.locations.list.filter(function (l) {
        return l.zone === zone && l.status !== "禁用" &&
          l.capacity - Number(l.used || 0) >= cubeOf(im.length, im.width, im.height,
            x.receivedQty);
      })[0] || DB.locations.list.filter(function (l) {
        return l.zone === "A" && l.status !== "禁用" &&
          l.capacity - Number(l.used || 0) >= cubeOf(im.length, im.width, im.height,
            x.receivedQty);
      })[0];
      a.tasks.push({ no: docNo([], "PT") + "-" + Math.floor(Math.random() * 90 + 10),
        asn_no: a.no, item: x.item, name: x.name, lot: x.lot, qty: x.receivedQty,
        from_loc: "F-01-01-1", to_loc: cand ? cand.code : "A-01-01-1",
        status: "待执行", operator: "", created_at: nowStr(), done_at: "" });
    });
    if (!a.tasks.length) return bad("没有可上架的收货明细");
    refreshAsn(a);
    log("生成上架任务", m[1] + " " + a.tasks.length + " 条");
    return ok({ no: a.no, created: a.tasks.length,
      tasks: a.tasks.map(function (t) {
        return { no: t.no, item: t.item, qty: t.qty, to: t.to_loc };
      }) });
  });
  on("GET", /^api\/putaway$/, function (m, qs) {
    var list = [];
    Object.keys(DB.asnD).forEach(function (no) {
      (DB.asnD[no].tasks || []).forEach(function (t) { list.push(t); });
    });
    if (qs.status && qs.status !== "全部") {
      list = list.filter(function (t) { return t.status === qs.status; });
    }
    list.sort(function (x, y) { return String(y.created_at).localeCompare(String(x.created_at)); });
    return ok({ list: list, total: list.length });
  });
  on("POST", /^api\/putaway\/([A-Za-z0-9\-]+)\/done$/, function (m, qs, b) {
    var task = null, asn = null;
    Object.keys(DB.asnD).forEach(function (no) {
      (DB.asnD[no].tasks || []).forEach(function (t) { if (t.no === m[1]) { task = t; asn = DB.asnD[no]; } });
    });
    if (!task) return bad("上架任务不存在：" + m[1], 404);
    if (task.status === "已完成") return bad("该上架任务已完成");
    var to = String(b.to || task.to_loc).toUpperCase();
    var loc = find(DB.locations.list, "code", to);
    if (!loc) return bad("目标货位不存在：" + to);
    var im = itemOf(task.item);
    var need = cubeOf(im.length, im.width, im.height, task.qty);
    if (loc.capacity - Number(loc.used || 0) + 1e-6 < need) {
      return bad("货位 " + to + " 容量不足：剩余 " +
        r2(loc.capacity - Number(loc.used || 0)) + " m³，需要 " + need + " m³");
    }
    addStock(task.item, task.lot, to, task.qty, im.price || 0, task.expiry || "");
    addMove("上架", task.item, task.lot, task.from_loc, to, task.qty, asn.no, "上架完成入账");
    task.status = "已完成"; task.to_loc = to; task.operator = DB.me.username;
    task.done_at = nowStr();
    var left = (asn.tasks || []).filter(function (t) { return t.status !== "已完成"; }).length;
    var qcBad = (asn.items || []).some(function (x) { return x.qcStatus === "不合格"; });
    if (left === 0 && !qcBad && ["已收货", "收货中"].indexOf(asn.status) >= 0) {
      asn.status = "已上架";
    }
    refreshAsn(asn);
    log("上架完成", task.no + " → " + to);
    return ok({ no: task.no, to: to, qty: task.qty, asnStatus: asn.status });
  });
  on("POST", /^api\/asns\/([A-Za-z0-9\-]+)\/cancel$/, function (m) {
    var a = DB.asnD[m[1]];
    if (!a) return bad("到货通知不存在", 404);
    a.status = "已取消";
    refreshAsn(a);
    log("取消到货通知", m[1]);
    return ok({ no: a.no, status: "已取消" });
  });

  /* ---- 出库 ---- */
  on("GET", /^api\/orders$/, function (m, qs) {
    var list = DB.orders.list;
    if (qs.status && qs.status !== "全部") {
      list = list.filter(function (x) { return x.status === qs.status; });
    }
    if (qs.q) list = need(list, qs);
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/orders\/([A-Za-z0-9\-]+)\/picklist$/, function (m) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    var lines = (o.allocations || []).map(function (x, i) {
      return { no: "PK-" + (i + 1), seq: i + 1, item: x.item, name: x.item, lot: x.lot,
        from_loc: x.location, qty: x.qty, status: "待拣" };
    });
    lines.sort(function (a, b) { return String(a.from_loc).localeCompare(String(b.from_loc)); });
    return ok({ no: o.no, customer: o.customerName, carrier: o.carrier,
      priority: o.priority, cutoff: o.cutoff, lines: lines,
      path: lines.map(function (x) { return x.from_loc; }),
      distance: r2(lines.length * 1.2), minutes: r2(lines.length * 0.35) });
  });
  on("GET", /^api\/orders\/([A-Za-z0-9\-]+)$/, function (m) {
    var d = DB.orderD[m[1]];
    return d ? ok(d) : bad("出库单不存在：" + m[1], 404);
  });
  on("POST", /^api\/orders$/, function (m, qs, b) {
    var cust = find(DB.customers.list, "code", b.customer);
    if (!cust) return bad("客户不存在：" + b.customer);
    if (cust.status !== "启用") return bad("客户已冻结，不能开单");
    if (!b.items || !b.items.length) return bad("出库单至少需要一行明细");
    var no = docNo(DB.orders.list, "SO");
    var o = { no: no, customer: b.customer, customerName: cust.name,
      customerLevel: cust.level || "", whCode: "WH-SZ01", type: b.type || "销售出库",
      priority: b.priority || "普通", cutoff: cust.cutoff || "18:00",
      carrier: b.carrier || cust.carrier || "CR-01", dest: cust.name + " 收货部",
      status: "草稿", waveNo: "", fillRate: 0, trackingNo: "", note: b.note || "",
      createdBy: DB.me.username, createdAt: nowStr(), submittedAt: "", shippedAt: "",
      signedAt: "", lineCount: 0, qty: 0, allocatedQty: 0, pickedQty: 0, shippedQty: 0,
      amount: 0, weight: 0, cube: 0, progress: 0, items: [], allocations: [],
      picks: [], packages: null, shipment: null, gate: null };
    var amount = 0;
    b.items.forEach(function (it, i) {
      var im = itemOf(it.item);
      if (!im.code) return bad("物料不存在：" + it.item);
      if (im.status !== "启用") return bad("物料 " + it.item + " 已停用");
      o.items.push({ line: i + 1, item: it.item, name: im.name || "", qty: Number(it.qty || 0),
        allocatedQty: 0, pickedQty: 0, shippedQty: 0, price: Number(im.price || 0),
        lot: "", location: "" });
      amount += Number(it.qty || 0) * Number(im.price || 0);
    });
    o.amount = r2(amount); o.lineCount = o.items.length; o.qty = r2(amount ? o.items.reduce(function (a, x) { return a + x.qty; }, 0) : 0);
    DB.orderD[no] = o;
    DB.orders.list.unshift({ no: no, customer: b.customer, customerName: cust.name,
      priority: o.priority, carrier: o.carrier, status: "草稿", waveNo: "",
      lineCount: o.lineCount, qty: o.qty, pickedQty: 0, fillRate: 0, trackingNo: "",
      createdAt: nowStr(), progress: 0 });
    refreshOrder(o);
    log("新建出库单", no);
    return ok({ no: no, lines: o.lineCount });
  });
  on("POST", /^api\/orders\/([A-Za-z0-9\-]+)\/stage$/, function (m, qs, b) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    var target = b.target;
    if (SO_FLOW.indexOf(target) < 0) return bad("目标状态不合法");
    if (["已分配", "拣货中", "已拣货"].indexOf(target) >= 0) {
      return bad("「" + target + "」请通过分配 / 波次 / 拣货动作完成");
    }
    if (idx(SO_FLOW, target) <= idx(SO_FLOW, o.status)) {
      return bad("不允许从「" + o.status + "」直接推进到「" + target + "」");
    }
    if (target === "已提交" && !o.submittedAt) o.submittedAt = nowStr();
    var g = soGate(target, o);
    if (g.miss.length) return bad("「" + target + "」闸口未通过：" + g.miss.join("；"));
    o.status = target;
    if (target === "已签收") {
      o.signedAt = nowStr();
      if (o.shipment) { o.shipment.status = "已签收"; o.shipment.signed_at = o.signedAt; }
    }
    refreshOrder(o);
    log("推进出库单", m[1] + " → " + target);
    return ok({ no: o.no, status: target });
  });
  on("POST", /^api\/orders\/([A-Za-z0-9\-]+)\/alloc$/, function (m) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    if (["已分配", "拣货中", "已拣货", "已复核", "已发运", "已签收", "已取消"].indexOf(o.status) >= 0 &&
        o.status !== "已分配") {
      return bad("当前状态「" + o.status + "」不能重新分配");
    }
    (o.allocations || []).forEach(function (a) {
      var s = findStock(a.item, a.lot, a.location);
      if (s) s.allocated = r2(Math.max(0, s.allocated - a.qty));
    });
    o.allocations = [];
    var totalNeed = 0, totalGot = 0;
    (o.items || []).forEach(function (row) {
      row.allocatedQty = 0; row.lot = ""; row.location = "";
      totalNeed += Number(row.qty || 0);
      var pool = stockRows().filter(function (s) {
        return s.item === row.item && Number(s.qty) > 0;
      }).map(function (s) {
        return { lot: s.lot, avail: r2(s.qty - s.allocated - s.frozen), expiry: s.expiry,
          location: s.location, s: s };
      }).filter(function (x) { return x.avail > 0; });
      pool.sort(function (a, b) {
        var da = a.expiry || "9999-12-31", db2 = b.expiry || "9999-12-31";
        return da < db2 ? -1 : (da > db2 ? 1 : 0);
      });
      var left = Number(row.qty || 0);
      pool.forEach(function (p) {
        if (left <= 1e-9) return;
        var take = r2(Math.min(left, p.avail));
        if (take <= 0) return;
        o.allocations.push({ order_no: o.no, line: row.line, item: row.item, lot: p.lot,
          location: p.location, qty: take, status: "已锁定", created_at: nowStr() });
        p.s.allocated = r2(Number(p.s.allocated) + take);
        row.allocatedQty = r2(Number(row.allocatedQty) + take);
        if (!row.lot) { row.lot = p.lot; row.location = p.location; }
        left = r2(left - take);
        totalGot += take;
      });
    });
    o.fillRate = r4(totalNeed ? totalGot / totalNeed : 1);
    o.status = o.fillRate >= 1 - 1e-9 ? "已分配" : "已提交";
    refreshOrder(o);
    log("库存分配", m[1] + " 满足率 " + Math.round(o.fillRate * 100) + "%");
    return ok({ no: o.no, fillRate: o.fillRate, strategy: "FEFO", short: [],
      status: o.status });
  });
  on("POST", /^api\/orders\/([A-Za-z0-9\-]+)\/pick$/, function (m) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    if (["已分配", "拣货中"].indexOf(o.status) < 0) {
      return bad("当前状态「" + o.status + "」不能拣货");
    }
    if (!(o.allocations || []).length) return bad("没有可拣的分配明细，请先做库存分配");
    var qty = 0;
    (o.allocations || []).forEach(function (a) {
      if (a.status === "已拣") return;
      takeStock(a.item, a.lot, a.location, a.qty);
      addMove("拣货出库", a.item, a.lot, a.location, "G-01-01-1", a.qty, o.no, "拣货下架");
      a.status = "已拣";
      qty += Number(a.qty || 0);
      var row = (o.items || []).filter(function (x) { return x.line === a.line; })[0];
      if (row) { row.pickedQty = r2(Number(row.pickedQty || 0) + a.qty); }
    });
    o.picks = o.allocations.map(function (a, i) {
      return { no: "PK-" + (i + 1), seq: i + 1, item: a.item, lot: a.lot,
        from_loc: a.location, qty: a.qty, status: "已拣" };
    });
    o.status = "已拣货";
    refreshOrder(o);
    log("拣货确认", m[1] + " / 拣出 " + r2(qty));
    return ok({ no: o.no, lines: o.allocations.length, qty: r2(qty), status: o.status });
  });
  on("POST", /^api\/orders\/([A-Za-z0-9\-]+)\/pack$/, function (m, qs, b) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    if (["已拣货", "已复核"].indexOf(o.status) < 0) {
      return bad("当前状态「" + o.status + "」不能复核打包");
    }
    var weight = 0, cube = 0;
    (o.items || []).forEach(function (x) {
      var im = itemOf(x.item);
      weight += Number(im.weight || 0) * Number(x.pickedQty || 0);
      cube += cubeOf(im.length, im.width, im.height, x.pickedQty || 0);
    });
    var boxes = Math.max(1, Math.ceil(cube / 0.06), Math.ceil(weight / 18));
    o.packages = { no: docNo([], "PKG"), order_no: o.no, boxes: Number(b.boxes || boxes),
      weight: r2(weight), cube: r4(cube), carrier: o.carrier, tracking_no: "",
      status: "已打包", operator: DB.me.username, created_at: nowStr() };
    o.status = "已复核";
    refreshOrder(o);
    log("复核打包", m[1] + " / " + o.packages.boxes + " 箱");
    return ok({ no: o.no, package: o.packages.no, boxes: o.packages.boxes,
      weight: r2(weight), cube: r4(cube), volWeight: r2(cube * 1e6 / 6000) });
  });
  on("POST", /^api\/orders\/([A-Za-z0-9\-]+)\/ship$/, function (m, qs, b) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    if (["已复核", "已发运"].indexOf(o.status) < 0) {
      return bad("当前状态「" + o.status + "」不能发运");
    }
    var carrier = b.carrier || o.carrier;
    if (!find(DB.carriers.list, "code", carrier)) return bad("承运商不存在：" + carrier);
    var tracking = b.trackingNo || ("FC" + String(Date.now()).slice(-13));
    o.trackingNo = tracking; o.carrier = carrier;
    if (o.packages) { o.packages.tracking_no = tracking; o.packages.status = "已发运"; }
    if (o.status === "已复核") {
      var weight = o.packages ? o.packages.weight : 0, cube = o.packages ? o.packages.cube : 0;
      o.shipment = { no: docNo([], "SH"), order_no: o.no, carrier: carrier,
        tracking_no: tracking, boxes: o.packages ? o.packages.boxes : 1,
        weight: weight, cost: r2(8 + weight * 1.2 + cube * 25), status: "已发运",
        operator: DB.me.username, shipped_at: nowStr(), signed_at: "" };
      (o.items || []).forEach(function (x) { x.shippedQty = x.pickedQty; });
      o.shippedAt = nowStr();
    }
    o.status = "已发运";
    refreshOrder(o);
    log("发运出库", m[1] + " / " + tracking);
    return ok({ no: o.no, trackingNo: tracking, carrier: carrier,
      boxes: o.packages ? o.packages.boxes : 1,
      cost: o.shipment ? o.shipment.cost : 0, status: o.status });
  });
  on("POST", /^api\/orders\/([A-Za-z0-9\-]+)\/cancel$/, function (m) {
    var o = DB.orderD[m[1]];
    if (!o) return bad("出库单不存在", 404);
    if (["草稿", "已提交", "已分配"].indexOf(o.status) < 0) {
      return bad("当前状态「" + o.status + "」不能取消");
    }
    (o.allocations || []).forEach(function (a) {
      var s = findStock(a.item, a.lot, a.location);
      if (s) s.allocated = r2(Math.max(0, s.allocated - a.qty));
      a.status = "已释放";
    });
    o.status = "已取消";
    refreshOrder(o);
    log("取消出库单", m[1]);
    return ok({ no: o.no, status: "已取消" });
  });

  /* ---- 波次 ---- */
  on("GET", /^api\/waves$/, function () {
    return ok({ list: DB.waves.list, total: DB.waves.list.length });
  });
  on("GET", /^api\/waves\/candidates$/, function () {
    var list = DB.orders.list.filter(function (x) {
      return x.status === "已分配" && !x.waveNo;
    });
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/waves\/([A-Za-z0-9\-]+)$/, function (m) {
    var w = find(DB.waves.list, "no", m[1]);
    if (!w) return bad("波次不存在", 404);
    var tasks = [];
    Object.keys(DB.orderD).forEach(function (no) {
      (DB.orderD[no].picks || []).forEach(function (p) {
        if (p.waveNo === m[1]) tasks.push(p);
      });
    });
    var v = clone(w);
    v.tasks = tasks;
    v.pickedLines = tasks.filter(function (t) { return t.status === "已拣"; }).length;
    v.pickedQty = r2(tasks.reduce(function (a, t) { return a + Number(t.picked_qty || 0); }, 0));
    v.distance = w.distance || 0;
    v.minutes = r2((tasks.length || 0) * 0.35);
    return ok(v);
  });
  on("POST", /^api\/waves$/, function (m, qs, b) {
    var rule = b.rule || "承运商";
    var nos = b.orders || DB.orders.list.filter(function (x) {
      return x.status === "已分配" && !x.waveNo;
    }).slice(0, 12).map(function (x) { return x.no; });
    if (!nos.length) return bad("没有可组波的订单（需先完成库存分配）");
    var groups = {};
    nos.forEach(function (no) {
      var o = DB.orderD[no];
      if (!o) return;
      if (o.status !== "已分配") { throw new Error("订单 " + no + " 尚未完成分配"); }
      if (o.waveNo) { throw new Error("订单 " + no + " 已在波次中"); }
      var k = rule === "客户" ? o.customer :
        (rule === "截单时段" ? (o.cutoff <= "12:00" ? "午前" : "午后") : o.carrier);
      (groups[k] = groups[k] || []).push(o);
    });
    var created = [];
    Object.keys(groups).forEach(function (k) {
      var wno = docNo(DB.waves.list, "WV");
      var orders = groups[k], lines = 0, tasks = [];
      orders.forEach(function (o) {
        o.waveNo = wno; o.status = "拣货中";
        (o.allocations || []).forEach(function (a) {
          if (a.status !== "已锁定") return;
          lines += 1;
          tasks.push({ no: "PK-" + wno + "-" + (tasks.length + 1), waveNo: wno,
            order_no: o.no, item: a.item, lot: a.lot, from_loc: a.location,
            qty: a.qty, picked_qty: 0, status: "待拣", seq: tasks.length + 1 });
        });
      });
      var w = { no: wno, rule: rule, carrier: orders[0].carrier, status: "待拣",
        orderCnt: orders.length, lineCnt: lines, cube: 0, weight: 0,
        operator: DB.me.username, createdAt: nowStr(), doneAt: "",
        orders: orders.map(function (o) {
          return { no: o.no, customer: o.customer, priority: o.priority, status: o.status };
        }), distance: r2(lines * 1.2) };
      DB.waves.list.unshift(w);
      created.push({ no: wno, orders: orders.map(function (o) { return o.no; }),
        lines: lines, carrier: w.carrier, distance: w.distance });
      tasks.sort(function (a, b) { return String(a.from_loc).localeCompare(String(b.from_loc)); });
      tasks.forEach(function (t, i) { t.seq = i + 1; });
      DB.__waveTasks = DB.__waveTasks || {};
      DB.__waveTasks[wno] = tasks;
    });
    log("生成波次", rule + " / " + created.length + " 个");
    return ok({ created: created.length, waves: created });
  });
  on("POST", /^api\/waves\/([A-Za-z0-9\-]+)\/release$/, function (m) {
    var w = find(DB.waves.list, "no", m[1]);
    if (!w) return bad("波次不存在", 404);
    if (w.status !== "待拣") return bad("波次状态为「" + w.status + "」，不能下发");
    w.status = "拣货中"; w.operator = DB.me.username;
    (DB.__waveTasks[w.no] || []).forEach(function (t) {
      if (t.status === "待拣") t.status = "拣货中";
    });
    log("下发波次", m[1]);
    return ok({ no: w.no, status: "拣货中" });
  });
  on("POST", /^api\/waves\/([A-Za-z0-9\-]+)\/pick$/, function (m) {
    var w = find(DB.waves.list, "no", m[1]);
    if (!w) return bad("波次不存在", 404);
    if (w.status === "已完成") return bad("波次已完成");
    var tasks = DB.__waveTasks[w.no] || [];
    var todo = tasks.filter(function (t) { return t.status !== "已拣"; });
    if (!todo.length) return bad("没有待拣任务");
    var done = 0, qty = 0;
    todo.forEach(function (t) {
      takeStock(t.item, t.lot, t.from_loc, t.qty);
      addMove("拣货出库", t.item, t.lot, t.from_loc, "G-01-01-1", t.qty, t.order_no,
        "波次 " + w.no + " 拣货");
      t.status = "已拣"; t.picked_qty = t.qty; t.operator = DB.me.username;
      done += 1; qty += Number(t.qty || 0);
      var o = DB.orderD[t.order_no];
      if (o) {
        var row = (o.items || []).filter(function (x) { return x.item === t.item; })[0];
        if (row) row.pickedQty = r2(Number(row.pickedQty || 0) + Number(t.qty));
        var alloc = (o.allocations || []).filter(function (a) {
          return a.item === t.item && a.lot === t.lot && a.location === t.from_loc;
        })[0];
        if (alloc) alloc.status = "已拣";
        var all = (o.items || []).every(function (x) {
          return Number(x.pickedQty || 0) >= Number(x.qty || 0) - 1e-9;
        });
        if (all) o.status = "已拣货";
        refreshOrder(o);
      }
    });
    w.status = "已完成"; w.doneAt = nowStr();
    log("波次拣货", w.no + " / " + done + " 行");
    return ok({ no: w.no, lines: done, qty: r2(qty), short: [], left: 0 });
  });
  on("POST", /^api\/waves\/([A-Za-z0-9\-]+)\/done$/, function (m) {
    var w = find(DB.waves.list, "no", m[1]);
    if (!w) return bad("波次不存在", 404);
    var left = (DB.__waveTasks[w.no] || []).filter(function (t) { return t.status !== "已拣"; }).length;
    if (left) return bad("还有 " + left + " 条拣货任务未完成");
    w.status = "已完成"; w.doneAt = nowStr();
    log("波次完成", m[1]);
    return ok({ no: w.no, status: "已完成" });
  });

  /* ---- 库存 ---- */
  on("GET", /^api\/stock$/, function (m, qs) {
    var list = stockRows();
    if (qs.location) list = list.filter(function (x) { return x.location === qs.location; });
    if (qs.q) list = need(list, qs);
    if (qs.filter === "avail") list = list.filter(function (x) { return Number(x.avail) > 0; });
    if (qs.filter === "expiry") list = list.filter(function (x) {
      return ["已过期", "临期"].indexOf(x.expiryLevel) >= 0;
    });
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/stock\/summary$/, function () {
    var by = {};
    stockRows().forEach(function (s) {
      var g = by[s.item] = by[s.item] || { item: s.item, name: s.name, unit: s.unit,
        abc: s.abc, qty: 0, allocated: 0, avail: 0, locCount: 0, amount: 0 };
      g.qty = r2(g.qty + Number(s.qty)); g.allocated = r2(g.allocated + Number(s.allocated));
      g.avail = r2(g.avail + Number(s.avail)); g.amount = r2(g.amount + Number(s.amount));
      g.locCount += 1;
    });
    var list = Object.keys(by).map(function (k) { return by[k]; });
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/lots$/, function (m, qs) {
    var list = DB.lots.list;
    if (qs.q) list = need(list, qs);
    return ok({ list: list.slice(0, Number(qs.limit || 12)), total: list.length });
  });
  on("GET", /^api\/moves$/, function (m, qs) {
    var list = DB.moves.list;
    if (qs.q) list = need(list, qs);
    return ok({ list: list.slice(0, Number(qs.limit || 50)), total: DB.moves.total || list.length });
  });
  on("GET", /^api\/expiry$/, function () {
    var buckets = { "已过期": 0, "临期": 0, "关注": 0, "正常": 0 };
    var list = [];
    DB.lots.list.forEach(function (l) {
      var lv = expLevel(l.expiry);
      buckets[lv] += 1;
      if (lv !== "正常") list.push({ lot: l.lot, item: l.item, name: l.name || "",
        expiry: l.expiry, daysLeft: daysLeft(l.expiry), level: lv,
        qty: l.qty || 0 });
    });
    list.sort(function (a, b) { return (a.daysLeft || 0) - (b.daysLeft || 0); });
    return ok({ buckets: buckets, list: list, total: list.length });
  });
  on("GET", /^api\/abc$/, function () {
    var rows = DB.items.list.map(function (x) {
      return { item: x.code, name: x.name, abc: x.abc, amount: r2(
        stockRows().filter(function (s) { return s.item === x.code; })
          .reduce(function (a, s) { return a + Number(s.amount || 0); }, 0)) };
    }).sort(function (a, b) { return b.amount - a.amount; });
    var total = rows.reduce(function (a, x) { return a + x.amount; }, 0), before = 0;
    rows.forEach(function (x) {
      var share = total ? x.amount / total : 0;
      x.share = r4(share);
      x.abc = before < 0.7 ? "A" : (before < 0.9 ? "B" : "C");
      before += share;
    });
    var stat = { A: { count: 0, amount: 0, share: 0 }, B: { count: 0, amount: 0, share: 0 },
      C: { count: 0, amount: 0, share: 0 } };
    rows.forEach(function (x) {
      stat[x.abc].count += 1; stat[x.abc].amount = r2(stat[x.abc].amount + x.amount);
      stat[x.abc].share = r4(stat[x.abc].share + x.share);
    });
    return ok({ list: rows, stat: stat, total: rows.length });
  });
  on("GET", /^api\/trace$/, function (m, qs) {
    if (qs.order && !qs.lot) {
      var lots = [];
      Object.keys(DB.orderD).forEach(function (no) {
        if (no !== qs.order) return;
        (DB.orderD[no].allocations || []).forEach(function (a) {
          if (a.lot && lots.indexOf(a.lot) < 0) lots.push(a.lot);
        });
      });
      return ok({ order: qs.order, lots: lots.map(traceLot) });
    }
    if (!qs.lot) return bad("请提供批次号（lot）或出库单号（order）");
    return ok(traceLot(qs.lot));
  });

  function traceLot(lot) {
    var l = find(DB.lots.list, "lot", lot);
    if (!l) { return { lot: lot, item: "?", name: "未知批次", inbound: [], outbound: [],
      stocks: [], moves: [], related: [], qtyIn: 0, qtyOut: 0, qty: 0, expiryLevel: "正常" }; }
    var moves = DB.moves.list.filter(function (x) { return x.lot === lot; });
    var inbound = moves.filter(function (x) {
      return x.type === "上架" || x.type === "收货";
    }).map(function (x) {
      var asn = DB.asnD[x.ref_no];
      return { move: x.no, ts: x.ts, type: x.type, qty: x.qty, asn: x.ref_no,
        supplier: asn ? asn.supplier : "", supplierName: asn ? asn.supplierName : "" };
    });
    var outbound = moves.filter(function (x) { return x.type === "拣货出库"; }).map(function (x) {
      var o = DB.orderD[x.ref_no];
      return { move: x.no, ts: x.ts, qty: x.qty, order: x.ref_no,
        customer: o ? o.customer : "", customerName: o ? o.customerName : "",
        carrier: o ? o.carrier : "", trackingNo: o ? o.trackingNo : "" };
    });
    var stocks = stockRows().filter(function (x) { return x.lot === lot; });
    var im = itemOf(l.item);
    return { lot: lot, item: l.item, name: im.name || l.name || "", abc: im.abc || "",
      unit: im.unit || "", storage: im.storage || "", price: r2(im.price || 0),
      qtyIn: r2(l.qtyIn || 0), qtyOut: r2(l.qtyOut || 0),
      qty: r2(stocks.reduce(function (a, s) { return a + Number(s.qty || 0); }, 0)),
      expiry: l.expiry, mfgDate: l.mfg_date || "", inboundAt: l.inbound_at || "",
      daysLeft: daysLeft(l.expiry), expiryLevel: expLevel(l.expiry),
      supplier: l.supplier || "", inbound: inbound, outbound: outbound,
      stocks: stocks, moves: moves, outQty: r2(outbound.reduce(function (a, x) {
        return a + Number(x.qty || 0); }, 0)),
      customers: outbound.map(function (x) { return x.customerName; })
        .filter(function (x, i, arr) { return x && arr.indexOf(x) === i; }),
      related: DB.lots.list.filter(function (x) {
        return x.item === l.item && x.lot !== lot;
      }).slice(0, 8).map(function (x) {
        return { lot: x.lot, expiry: x.expiry, qty: x.qty || 0 };
      }) };
  }

  /* ---- 库内作业 ---- */
  on("GET", /^api\/stocktakes$/, function (m, qs) {
    var list = DB.stocktakes.list;
    if (qs.status && qs.status !== "全部") {
      list = list.filter(function (x) { return x.status === qs.status; });
    }
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/stocktakes\/([A-Za-z0-9\-]+)$/, function (m) {
    var t = DB.stD[m[1]];
    return t ? ok(t) : bad("盘点单不存在", 404);
  });
  on("POST", /^api\/stocktakes$/, function (m, qs, b) {
    var zone = b.zone || "";
    var rows = stockRows().filter(function (s) {
      return !zone || s.location.indexOf(zone + "-") === 0;
    });
    if (!rows.length) return bad("该库区没有库存，无需盘点");
    var no = docNo(DB.stocktakes.list, "ST");
    var t = { no: no, whCode: "WH-SZ01", zone: zone, type: b.type || "明盘",
      status: "盘点中", operator: DB.me.username, createdAt: nowStr(), countedAt: "",
      approveBy: "", diffLines: 0, diffAmount: 0, note: b.note || "", lineCount: 0,
      diffCount: 0, countedAll: false, items: [], gate: null, adjusted: false };
    rows.forEach(function (s) {
      t.items.push({ id: -Math.floor(Math.random() * 1e9), location: s.location,
        item: s.item, name: s.name, lot: s.lot, bookQty: s.qty,
        actualQty: b.type === "盲盘" ? 0 : s.qty,
        diffQty: 0, price: s.price, amount: 0, result: "待盘", status: "待盘" });
    });
    DB.stD[no] = t;
    DB.stocktakes.list.unshift({ no: no, zone: zone || "全仓", type: t.type,
      status: "盘点中", lineCount: t.items.length, diffLines: 0, diffAmount: 0,
      createdAt: nowStr() });
    refreshSt(t);
    log("发起盘点", no + " / " + (zone || "全仓") + " " + t.items.length + " 行");
    return ok({ no: no, lines: t.items.length, type: t.type, status: "盘点中" });
  });
  on("POST", /^api\/stocktakes\/([A-Za-z0-9\-]+)\/count$/, function (m, qs, b) {
    var t = DB.stD[m[1]];
    if (!t) return bad("盘点单不存在", 404);
    if (t.status !== "盘点中") return bad("盘点单状态为「" + t.status + "」，不能录入");
    var done = 0;
    (b.items || []).forEach(function (x) {
      var row = (t.items || []).filter(function (y) { return y.id === x.id; })[0];
      if (!row) return;
      row.actualQty = Number(x.actualQty !== undefined ? x.actualQty : row.bookQty);
      row.diffQty = r2(row.actualQty - row.bookQty);
      row.result = Math.abs(row.diffQty) < 1e-9 ? "盘平" : (row.diffQty > 0 ? "盘盈" : "盘亏");
      row.status = "已盘";
      done += 1;
    });
    var diff = (t.items || []).filter(function (x) { return Math.abs(x.diffQty) > 1e-9; });
    t.diffLines = diff.length;
    t.diffAmount = r2(diff.reduce(function (a, x) { return a + x.diffQty * x.price; }, 0));
    t.countedAt = nowStr();
    refreshSt(t);
    log("盘点录入", m[1] + " / " + done + " 行");
    return ok({ no: t.no, counted: done, diffLines: t.diffLines, diffAmount: t.diffAmount });
  });
  on("POST", /^api\/stocktakes\/([A-Za-z0-9\-]+)\/stage$/, function (m, qs, b) {
    var t = DB.stD[m[1]];
    if (!t) return bad("盘点单不存在", 404);
    var target = b.target;
    if (ST_FLOW.indexOf(target) < 0) return bad("目标状态不合法");
    if (idx(ST_FLOW, target) <= idx(ST_FLOW, t.status)) {
      return bad("不允许从「" + t.status + "」推进到「" + target + "」");
    }
    var ctx = stCtx(t);
    if (target === "已调整" && ctx.diffLines > 0) t.adjusted = true;
    if (target === "已调整") t.approveBy = DB.me.username;
    var miss = [];
    if (target === "待审核" && !ctx.countedAll) miss.push("仍有货位未录入实盘数");
    if (target === "已调整") {
      if (ctx.diffLines > 0 && !t.adjusted) miss.push("存在差异行但未生成库存调整");
    }
    if (target === "已关闭" && t.status !== "已调整") miss.push("盘点单未完成调整");
    if (miss.length) return bad("「" + target + "」闸口未通过：" + miss.join("；"));
    if (target === "已调整") {
      var n = 0;
      (t.items || []).forEach(function (x) {
        if (Math.abs(Number(x.diffQty || 0)) <= 1e-9) return;
        var s = findStock(x.item, x.lot, x.location);
        if (s) {
          var d = Number(x.diffQty);
          s.qty = r2(Number(s.qty) + d);
          s.avail = r2(s.qty - s.allocated - s.frozen);
          s.amount = r2(s.qty * s.price);
        }
        addMove(Number(x.diffQty) > 0 ? "盘盈" : "盘亏", x.item, x.lot, x.location,
          x.location, Math.abs(Number(x.diffQty)), t.no, "盘点差异调整");
        n += 1;
      });
      t.adjusted = true;
      t.approveBy = DB.me.username;
      refreshSt(t);
      log("盘点调整", t.no + " / " + n + " 行差异");
      return ok({ no: t.no, status: target, adjusted: n });
    }
    t.status = target;
    refreshSt(t);
    log("推进盘点", t.no + " → " + target);
    return ok({ no: t.no, status: target });
  });

  on("GET", /^api\/replenish$/, function () { return ok(DB.replenish); });
  on("POST", /^api\/replenish$/, function (m, qs, b) {
    if (!b.item || !(Number(b.qty) > 0)) return bad("物料与补货数量不能为空");
    var no = docNo(DB.replenish.tasks, "RP");
    var src = stockRows().filter(function (s) {
      return s.item === b.item && s.location.indexOf("A-") === 0 && Number(s.qty) >= b.qty;
    }).sort(function (a, x) { return x.qty - a.qty; })[0];
    if (!src) return bad("存储区没有足够库存可供补货");
    var to = b.to || (stockRows().filter(function (s) {
      return s.item === b.item && s.location.indexOf("B-") === 0;
    })[0] || {}).location;
    if (!to) return bad("该物料没有拣货位，请先指定目标拣货位");
    var t = { no: no, item: b.item, name: src.name, from_loc: src.location, to_loc: to,
      qty: Number(b.qty), status: "待执行", operator: "", created_at: nowStr(), done_at: "" };
    DB.replenish.tasks.unshift(t);
    DB.replenish.pending += 1;
    log("生成补货任务", no + " / " + b.item);
    return ok({ no: no, item: b.item, qty: Number(b.qty), from: src.location, to: to });
  });
  on("POST", /^api\/replenish\/([A-Za-z0-9\-]+)\/done$/, function (m, qs, b) {
    var t = find(DB.replenish.tasks, "no", m[1]);
    if (!t) return bad("补货任务不存在", 404);
    if (t.status === "已完成") return bad("该补货任务已完成");
    var qty = Number(b.qty || t.qty);
    var src = findStock(t.item, (findStock(t.item, "", t.from_loc) || {}).lot, t.from_loc);
    if (!src || Number(src.qty) < qty) return bad("存储区库存不足，无法补货");
    var lot = src.lot;
    takeStock(t.item, lot, t.from_loc, qty);
    addStock(t.item, lot, t.to_loc, qty, src.price, src.expiry);
    addMove("补货", t.item, lot, t.from_loc, t.to_loc, qty, t.no, "拣货面补货");
    t.status = "已完成"; t.operator = DB.me.username; t.done_at = nowStr();
    DB.replenish.pending = Math.max(0, (DB.replenish.pending || 1) - 1);
    log("补货完成", t.no + " / " + t.item + " " + qty);
    return ok({ no: t.no, status: "已完成", qty: qty });
  });
  on("GET", /^api\/transfers$/, function () {
    return ok({ list: DB.transfers.list, total: DB.transfers.list.length });
  });
  on("POST", /^api\/transfers$/, function (m, qs, b) {
    if (!b.item || !b.from || !b.to || !(Number(b.qty) > 0)) {
      return bad("物料、源货位、目标货位、数量都必须填写");
    }
    if (b.from === b.to) return bad("源货位与目标货位相同");
    if (!find(DB.locations.list, "code", b.to)) return bad("目标货位不存在：" + b.to);
    var s = find(DB.locations.list, "code", b.from);
    var row = stockRows().filter(function (x) {
      return x.item === b.item && x.location === b.from && Number(x.qty) >= Number(b.qty);
    })[0];
    if (!row) return bad("源货位没有足够的该物料库存");
    takeStock(b.item, row.lot, b.from, Number(b.qty));
    addStock(b.item, row.lot, b.to, Number(b.qty), row.price, row.expiry);
    var no = docNo(DB.transfers.list, "MV");
    DB.transfers.list.unshift({ no: no, item: b.item, lot: row.lot, from_loc: b.from,
      to_loc: b.to, qty: Number(b.qty), status: "已完成", operator: DB.me.username,
      created_at: nowStr() });
    addMove("移库", b.item, row.lot, b.from, b.to, Number(b.qty), no, b.note || "库内移库");
    log("库内移库", b.item + " " + b.from + " → " + b.to);
    return ok({ no: no, item: b.item, from: b.from, to: b.to, qty: Number(b.qty) });
  });
  on("POST", /^api\/moves$/, function (m, qs, b) {
    var types = ["移库", "盘盈", "盘亏", "调整", "退货入库", "报废"];
    if (types.indexOf(b.type) < 0) return bad("流水类型不合法：" + b.type);
    if (!b.item || !(Number(b.qty) > 0)) return bad("物料与数量不能为空");
    var qty = Number(b.qty);
    var row = stockRows().filter(function (x) {
      return x.item === b.item && (!b.lot || x.lot === b.lot) &&
        (!b.from || x.location === b.from);
    })[0];
    if (b.type !== "盘盈" && !row) return bad("源库存行不存在");
    if (row) {
      var lot = b.lot || row.lot;
      if (b.type === "移库" || b.type === "退货入库") {
        if (b.type === "移库") takeStock(b.item, lot, b.from, qty);
        addStock(b.item, lot, b.to, qty, row.price, row.expiry);
      } else if (b.type === "盘亏" || b.type === "报废") {
        takeStock(b.item, lot, b.from, qty);
      } else if (b.type === "盘盈") {
        addStock(b.item, lot, b.to || b.from || "A-01-01-1", qty, row.price, row.expiry);
      }
      addMove(b.type, b.item, lot, b.from || "", b.to || "", qty, b.ref || "", b.note || "手工操作");
      return ok({ type: b.type, item: b.item, lot: lot, qty: qty, from: b.from || "",
        to: b.to || "" });
    }
    return bad("源库存行不存在");
  });
  on("GET", /^api\/exceptions$/, function () {
    return ok({ list: DB.exceptions.list, total: DB.exceptions.list.length });
  });

  /* ---- 看板与报表 ---- */
  on("GET", /^api\/board$/, function () { refreshBoot(); return ok(DB.board); });
  on("GET", /^api\/reports$/, function (m, qs) { return ok(DB.reports); });

  /* ---- 设置 ---- */
  on("GET", /^api\/settings$/, function () { return ok(DB.settings); });
  on("PUT", /^api\/settings$/, function () { return ok({ saved: true }); });
  on("GET", /^api\/rules$/, function () {
    return ok({ list: DB.settings.rules });
  });
  on("PUT", /^api\/rules\/([a-z0-9_]+)$/, function (m, qs, b) {
    var r = find(DB.settings.rules, "code", m[1]);
    if (!r) return bad("规则不存在：" + m[1], 404);
    r.value = Number(b.value);
    log("调整规则", r.name + " = " + r.value);
    return ok({ code: r.code, value: r.value });
  });
  on("GET", /^api\/logs$/, function (m, qs) {
    var list = DB.__logs;
    return ok({ list: list.slice(0, Number(qs.limit || 200)), total: list.length + 200 });
  });
  on("GET", /^api\/users$/, function () {
    return ok({ list: DB.settings.users, total: DB.settings.users.length });
  });
  on("POST", /^api\/users$/, function (m, qs, b) {
    if (!b.username) return bad("用户名不能为空");
    if (find(DB.settings.users, "username", b.username)) return bad("用户名已存在");
    var rec = { username: b.username, displayName: b.displayName || b.username,
      role: b.role || "viewer", roleLabel: (b.role || "viewer") === "admin" ? "系统管理员" : "业务角色",
      dept: b.dept || "", status: "启用", createdAt: nowStr() };
    DB.settings.users.unshift(rec);
    log("新建账号", b.username);
    return ok({ username: rec.username, created: true });
  });

  /* ---- 集成 ---- */
  on("GET", /^api\/integration\/overview$/, function () { return ok(DB.integ.overview); });
  on("GET", /^api\/integration\/keys$/, function () {
    var list = DB.integ.keys.list;
    return ok({ list: list, active: list.filter(function (x) { return x.status === "启用"; }).length });
  });
  on("POST", /^api\/integration\/keys$/, function (m, qs, b) {
    if (!b.name) return bad("Key 名称不能为空");
    DB.__keySeq += 1;
    var raw = "fck_" + Math.random().toString(36).slice(2, 12) +
      Math.random().toString(36).slice(2, 8);
    var rec = { id: DB.__keySeq, name: b.name, prefix: raw.slice(0, 12),
      scope: b.scope || "read", owner: DB.me.username, status: "启用",
      createdAt: nowStr(), lastUsedAt: "", expiresAt: "" };
    DB.integ.keys.list.unshift(rec);
    log("创建 API Key", b.name);
    return ok({ id: rec.id, key: raw, name: b.name, scope: rec.scope,
      notice: "密钥只显示一次，请立即保存（DEMO 中刷新即失效）" });
  });
  on("DELETE", /^api\/integration\/keys\/(\d+)$/, function (m) {
    var rec = find(DB.integ.keys.list, "id", Number(m[1]));
    if (!rec) return bad("Key 不存在", 404);
    rec.status = "吊销";
    log("吊销 API Key", rec.name);
    return ok({ id: rec.id, status: rec.status });
  });
  on("GET", /^api\/integration\/webhooks$/, function () {
    return ok({ list: DB.integ.webhooks.list, total: DB.integ.webhooks.list.length });
  });
  on("POST", /^api\/integration\/webhooks$/, function (m, qs, b) {
    if (!b.name || !b.url) return bad("名称与回调地址不能为空");
    DB.__hookSeq += 1;
    var rec = { id: DB.__hookSeq, name: b.name, url: b.url, events: b.events || [],
      status: "启用", secret: "whsec_demo" + Math.random().toString(36).slice(2, 10),
      createdAt: nowStr(), deliveries: 0 };
    DB.integ.webhooks.list.unshift(rec);
    log("创建 Webhook", b.name);
    return ok({ id: rec.id, name: rec.name, events: rec.events, secret: rec.secret,
      notice: "签名密钥只显示一次，请妥善保存" });
  });
  on("PUT", /^api\/integration\/webhooks\/(\d+)$/, function (m, qs, b) {
    var rec = find(DB.integ.webhooks.list, "id", Number(m[1]));
    if (!rec) return bad("Webhook 不存在", 404);
    if (b.status) rec.status = b.status;
    if (b.events) rec.events = b.events;
    log("修改 Webhook", rec.name);
    return ok({ id: rec.id, status: rec.status });
  });
  on("DELETE", /^api\/integration\/webhooks\/(\d+)$/, function (m) {
    var id = Number(m[1]);
    DB.integ.webhooks.list = DB.integ.webhooks.list.filter(function (x) { return x.id !== id; });
    log("删除 Webhook", String(id));
    return ok({ id: id, deleted: true });
  });
  on("POST", /^api\/integration\/test$/, function () {
    var n = 0;
    DB.integ.webhooks.list.forEach(function (h) {
      if (h.status !== "启用") return;
      DB.__dlvSeq += 1;
      DB.integ.deliveries.list.unshift({ id: DB.__dlvSeq, webhookId: h.id,
        webhookName: h.name, event: "test.ping", status: "失败", attempts: 1, httpCode: 0,
        error: "离线演示环境无外网，投递记为失败", createdAt: nowStr(), deliveredAt: "" });
      h.deliveries = Number(h.deliveries || 0) + 1;
      n += 1;
    });
    log("测试事件", "test.ping × " + n);
    return ok({ event: "test.ping", queued: n });
  });
  on("GET", /^api\/integration\/deliveries$/, function () {
    var list = DB.integ.deliveries.list;
    return ok({ list: list, total: list.length,
      failed: list.filter(function (x) { return x.status === "失败"; }).length });
  });
  on("POST", /^api\/integration\/deliveries\/(\d+)\/retry$/, function (m) {
    var rec = find(DB.integ.deliveries.list, "id", Number(m[1]));
    if (!rec) return bad("投递记录不存在", 404);
    rec.attempts = Number(rec.attempts || 0) + 1;
    log("重投事件", rec.event + " #" + rec.id);
    return ok({ id: rec.id, attempts: rec.attempts, status: rec.status });
  });
  on("GET", /^api\/integration\/mappings$/, function () {
    return ok({ list: DB.integ.mappings.list, total: DB.integ.mappings.list.length });
  });
  on("POST", /^api\/integration\/mappings$/, function (m, qs, b) {
    if (!b.system || !b.objType || !b.extId || !b.localId) {
      return bad("系统、对象类型、外部 ID、本地 ID 都不能为空");
    }
    DB.__mapSeq += 1;
    var rec = { id: DB.__mapSeq, system: b.system, obj_type: b.objType,
      ext_id: b.extId, local_id: b.localId, created_at: nowStr() };
    DB.integ.mappings.list.unshift(rec);
    log("新增外部映射", b.extId);
    return ok({ id: rec.id });
  });
  on("POST", /^api\/integration\/resolve$/, function (m, qs, b) {
    var rec = DB.integ.mappings.list.filter(function (x) {
      return x.system === b.system && x.obj_type === b.objType &&
        (b.extId ? x.ext_id === b.extId : x.local_id === b.localId);
    })[0];
    if (b.extId) return ok({ found: !!rec, localId: rec ? rec.local_id : "", mapping: rec || {} });
    return ok({ found: !!rec, extId: rec ? rec.ext_id : "", mapping: rec || {} });
  });
  on("GET", /^api\/sync\/changes$/, function (m, qs) {
    var since = Number(qs.since || 0), limit = Math.min(500, Number(qs.limit || 100));
    var rows = DB.__changes.filter(function (c) { return c.id > since; }).slice(0, limit);
    var cursor = rows.length ? rows[rows.length - 1].id : since;
    return ok({ list: rows, cursor: cursor, count: rows.length,
      hasMore: DB.__changes.some(function (c) { return c.id > cursor; }),
      objects: ["asn", "order", "stock", "op"] });
  });
  on("GET", /^api\/health$/, function () {
    return ok({ status: "up", app: "飞传WMS", version: "1.0.0", mode: "demo", time: nowStr() });
  });

  /* ------------------------------------------------------------ fetch 拦截 */
  var _fetch = window.fetch;
  window.fetch = function (input, opt) {
    opt = opt || {};
    var url = String(input);
    var mp = url.match(/api\/[^?#]+/);
    if (!mp) return _fetch ? _fetch(input, opt) : Promise.reject(new Error("no fetch"));
    var path = mp[0].replace(/^\//, "");
    var qs = {};
    var q2 = url.split("?")[1] || "";
    q2.split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      qs[decodeURIComponent(i < 0 ? kv : kv.slice(0, i))] =
        decodeURIComponent(i < 0 ? "" : kv.slice(i + 1).replace(/\+/g, " "));
    });
    if (path.indexOf("?") >= 0) path = path.slice(0, path.indexOf("?"));
    var method = String(opt.method || "GET").toUpperCase();
    var body = {};
    if (opt.body) { try { body = JSON.parse(opt.body); } catch (e) { body = {}; } }
    var result = null;
    try {
      for (var i = 0; i < ROUTES.length; i++) {
        var r = ROUTES[i];
        if (r[0] !== method) continue;
        var m2 = path.match(r[1]);
        if (!m2) continue;
        result = r[2](m2, qs, body);
        break;
      }
    } catch (e) {
      result = bad(e.message || "服务异常", 400);
    }
    if (!result) result = bad("接口未实现（DEMO）：" + method + " " + path, 404);
    persist();
    var resp = {
      ok: result.status < 400,
      status: result.status,
      json: function () { return Promise.resolve(result.body); },
      text: function () { return Promise.resolve(JSON.stringify(result.body)); }
    };
    return Promise.resolve(resp);
  };

  /* CSV 导出（内存生成） */
  var _open = window.open;
  window.open = function (u) {
    if (String(u).indexOf("/api/export/orders.csv") === 0) {
      var lines = [["出库单号", "客户", "优先级", "承运商", "状态", "行数", "数量", "已拣",
        "满足率", "运单号", "创建时间"].join(",")];
      DB.orders.list.forEach(function (o) {
        lines.push([o.no, o.customerName, o.priority, o.carrier, o.status, o.lineCount,
          o.qty, o.pickedQty, Math.round(Number(o.fillRate || 0) * 100) + "%",
          o.trackingNo || "", o.createdAt].join(","));
      });
      var blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "feichuan_orders.csv";
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 800);
      return null;
    }
    if (String(u).indexOf("/api/export/stock.csv") === 0) {
      var rows = [["物料编码", "物料名称", "批次", "货位", "数量", "锁定", "可用", "金额",
        "有效期"].join(",")];
      stockRows().forEach(function (s) {
        rows.push([s.item, s.name, s.lot, s.location, s.qty, s.allocated, s.avail,
          s.amount, s.expiry || ""].join(","));
      });
      var blob2 = new Blob(["\ufeff" + rows.join("\n")], { type: "text/csv;charset=utf-8" });
      var a2 = document.createElement("a");
      a2.href = URL.createObjectURL(blob2);
      a2.download = "feichuan_stock.csv";
      document.body.appendChild(a2);
      a2.click();
      setTimeout(function () { URL.revokeObjectURL(a2.href); a2.remove(); }, 800);
      return null;
    }
    return _open ? _open.apply(window, arguments) : null;
  };

  /* 绕过登录页 */
  try {
    localStorage.setItem("wms_token", "demo-token");
    localStorage.setItem("fc_user", "admin");
    localStorage.setItem("fc_name", "系统管理员");
    localStorage.setItem("fc_role", "admin");
    localStorage.setItem("fc_role_label", "系统管理员");
  } catch (e) { /* 隐私模式忽略 */
  }
})();
