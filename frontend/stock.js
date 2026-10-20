/* 飞传 WMS · 库存台账、库位管理、补货与移库 */
(function (window, document) {
  "use strict";
  var F = window.F;

  /* ============================================================ 库存台账 */
  F.register("stock", function (params) {
    var tab = params.tab || "detail";
    var only = params.only || "";
    var q = params.q || "";

    function load() {
      var qs = "?limit=200" + (only ? "&only=" + only : "") +
        (q ? "&q=" + encodeURIComponent(q) : "");
      Promise.all([
        tab === "detail" ? F.api("GET", "/api/stock" + qs)
          : F.api("GET", "/api/stock/summary" + (q ? "?q=" + encodeURIComponent(q) : "")),
        F.api("GET", "/api/expiry?days=30")
      ]).then(function (res) {
        var d = res[0], ex = res[1];
        var s = d.summary || { qty: 0, value: 0, sku: 0, lots: 0, locs: 0, allocated: 0 };
        var html = '<div class="panel"><div class="panel-title">库存台账' +
          '<span class="panel-actions">' +
          '<input class="inp sm" id="stQ" placeholder="物料/批次/货位" value="' + F.esc(q) + '">' +
          '<button class="btn sm" id="stGo">查询</button>' +
          '<a class="btn sm" href="api/export/stock.csv" target="_blank">导出 CSV</a>' +
          "</span></div><div class=\"panel-body\"><div class=\"kpi-grid four\">" +
          '<div class="kpi"><div class="k-label">在库数量</div><div class="k-value">' +
          F.wan(s.qty) + '</div><div class="k-sub">锁定 ' + F.qty(s.allocated) + " 件</div></div>" +
          '<div class="kpi green"><div class="k-label">库存货值</div><div class="k-value">' +
          F.wan(s.value) + '</div><div class="k-sub">' + s.sku + " 个 SKU · " + s.lots +
          " 个批次</div></div>" +
          '<div class="kpi"><div class="k-label">占用货位</div><div class="k-value">' + s.locs +
          '</div><div class="k-sub">平均 ' + F.qty(s.locs ? s.qty / s.locs : 0) + " 件/货位</div></div>" +
          '<div class="kpi gold"><div class="k-label">30 天临期</div><div class="k-value">' +
          ex.total + '</div><div class="k-sub">数量 ' + F.qty(ex.qty) + " · 货值 " +
          F.wan(ex.amount) + "</div></div></div>" +
          F.chips([["detail", "批次明细 (" + (tab === "detail" ? d.total : "…") + ")"],
            ["summary", "按物料汇总"]], tab, "data-tab") +
          (tab === "detail" ? F.chips([["", "全部"], ["available", "仅可用"], ["expiry", "临期 30 天"]],
            only, "data-only") : "") +
          "</div></div>";

        html += '<div class="panel"><div class="panel-title">' +
          (tab === "detail" ? "库存明细（批次 + 货位）" : "按物料汇总") +
          '<span class="panel-actions small muted">' +
          (tab === "detail" ? "点击行查看批次追溯" : "按库存金额降序") + "</span></div>" +
          "<div class='panel-body flush' id='stBody'></div></div>";
        document.getElementById("view").innerHTML = html;

        var body = document.getElementById("stBody");
        if (tab === "detail") {
          body.innerHTML = F.table([
            { label: "物料", render: function (r) { return F.tag(r.abc, r.abc === "A" ? "green" :
              (r.abc === "B" ? "blue" : "gold")) + ' <b class="small">' + F.esc(r.item) + "</b>" +
              '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "货位", render: function (r) { return '<span class="mono">' + F.esc(r.location) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return '<b>' + F.qty(r.qty) + "</b> " +
              '<span class="muted small">' + F.esc(r.unit) + "</span>"; } },
            { label: "锁定", num: true, render: function (r) { return r.allocated ? F.qty(r.allocated) : "—"; } },
            { label: "可用", num: true, render: function (r) { return F.qty(r.avail); } },
            { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
            { label: "有效期", render: function (r) {
              if (!r.expiry) return '<span class="muted small">—</span>';
              return '<span class="small">' + F.esc(r.expiry) + "</span><div>" +
                F.tag(r.daysLeft + " 天", r.expiryLevel === "已过期" ? "red" :
                  (r.expiryLevel === "临期" ? "gold" : "gray")) + "</div>";
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], d.list, { click: function (r) { return r.lot; }, empty: "没有匹配的库存" });
          F.bindRows(document, function (lot) { F.go("trace", { lot: lot }); });
        } else {
          body.innerHTML = F.table([
            { label: "物料", render: function (r) { return F.tag(r.abc, r.abc === "A" ? "green" :
              (r.abc === "B" ? "blue" : "gold")) + ' <b class="small">' + F.esc(r.item) + "</b>" +
              '<div class="muted small">' + F.esc(r.name) + " · " + F.esc(r.category) + "</div>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "锁定", num: true, render: function (r) { return r.allocated ? F.qty(r.allocated) : "—"; } },
            { label: "货值", num: true, render: function (r) { return F.wan(r.amount); } },
            { label: "批次/货位", num: true, render: function (r) {
              return r.lotCount + " / " + r.locCount;
            } },
            { label: "水位", render: function (r) { return F.tag(r.level) +
              '<div class="muted small">安全 ' + F.qty(r.safety) + "</div>"; } },
            { label: "最近效期", render: function (r) { return r.expiry ?
              '<span class="small">' + F.esc(r.expiry) + '</span><div class="muted small">剩 ' +
              (r.daysLeft === null ? "—" : r.daysLeft + " 天") + "</div>" :
              '<span class="muted small">—</span>'; } },
            { label: "", render: function (r) { return '<a class="btn sm" href="#items">详情</a>'; } }
          ], d.list, { empty: "没有匹配的物料" });
        }

        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("stock", { tab: b.getAttribute("data-tab"), q: q, only: only });
          });
        });
        document.querySelectorAll("[data-only]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("stock", { tab: "detail", only: b.getAttribute("data-only"), q: q });
          });
        });
        document.getElementById("stGo").addEventListener("click", function () {
          F.go("stock", { tab: tab, only: only, q: document.getElementById("stQ").value.trim() });
        });

        F.setSide('<div class="side-block"><div class="hd">库存口径</div><div class="bd small" ' +
          'style="line-height:1.9">可用量 = 现有量 − 已锁定 − 冻结量。批次按有效期升序排列，' +
          '分配默认 FEFO（先到期先出），可在基础设置里切换 FIFO / LIFO。</div></div>' +
          '<div class="side-block"><div class="hd">临期分布</div><div class="bd">' +
          F.kv("已过期批次", ex.buckets["已过期"] || 0) +
          F.kv("临期（≤30 天）", ex.buckets["临期"] || 0) +
          F.kv("关注（≤90 天）", ex.buckets["关注"] || 0) +
          "</div></div>");
        F.setStatus("库存台账 · " + (d.total || 0) + " 条记录");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });

  /* ============================================================ 库位管理 */
  F.register("locations", function (params) {
    var zone = params.zone || "";

    function load() {
      Promise.all([
        F.api("GET", "/api/locations?limit=400"),
        F.api("GET", "/api/zones")
      ]).then(function (res) {
        var d = res[0], z = res[1];
        var list = d.list || [];
        var zones = z.list || [];
        var shown = zone ? list.filter(function (x) { return x.zone === zone; }) : list;
        var busy = list.filter(function (x) { return x.used > 0; }).length;
        var cap = list.reduce(function (a, x) { return a + x.capacity; }, 0);
        var used = list.reduce(function (a, x) { return a + x.used; }, 0);

        var html = '<div class="panel"><div class="panel-title">库位管理' +
          '<span class="panel-actions small muted">共 ' + list.length + " 个货位</span></div>" +
          '<div class="panel-body"><div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">货位总数</div><div class="k-value">' + list.length +
          '</div><div class="k-sub">占用 ' + busy + " · 空闲 " + (list.length - busy) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">货位占用率</div><div class="k-value">' +
          F.pct(busy / Math.max(1, list.length), 0) + '</div><div class="k-sub">有货货位占比</div></div>' +
          '<div class="kpi"><div class="k-label">总容量</div><div class="k-value">' + F.cube(cap) +
          '</div><div class="k-sub">已用 ' + F.cube(used) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">体积利用率</div><div class="k-value">' +
          F.pct(used / Math.max(0.001, cap), 1) + '</div><div class="k-sub">超过 90% 建议调整</div></div>' +
          "</div>" + F.chips([["", "全部库区"]].concat(zones.map(function (x) {
            return [x.code, x.code + " " + x.kind, x.locCount];
          })), zone, "data-zone") + "</div></div>";

        html += '<div class="panel"><div class="panel-title">库区负荷' +
          '<span class="panel-actions small muted">颜色越深占用越高</span></div>' +
          '<div class="panel-body"><div class="zone-cards">' +
          zones.map(function (x) {
            return '<div class="zone-card' + (x.code === zone ? " on" : "") + '" data-z="' + F.esc(x.code) + '">' +
              '<div class="zc-hd"><b>' + F.esc(x.code) + "</b><span>" + F.esc(x.kind) + "</span></div>" +
              '<div class="zc-name">' + F.esc(x.name) + "</div>" +
              F.progress(x.util) +
              '<div class="zc-ft"><span>' + F.pct(x.util, 0) + " 体积</span><span>" +
              F.qty(x.stockQty) + " 件</span><span>" + x.locCount + " 位</span></div></div>";
          }).join("") + "</div>";
        html += '<div class="loc-legend"><span><i class="lv0"></i>空闲</span>' +
          '<span><i class="lv1"></i>&lt;30%</span><span><i class="lv2"></i>30~70%</span>' +
          '<span><i class="lv3"></i>70~90%</span><span><i class="lv4"></i>&gt;90%</span></div>';
        html += '<div class="loc-grid">' + shown.map(function (x) {
          var lv = x.used <= 0 ? 0 : (x.util < 0.3 ? 1 : (x.util < 0.7 ? 2 : (x.util < 0.9 ? 3 : 4)));
          return '<div class="loc-cell lv' + lv + '" data-loc="' + F.esc(x.code) + '" title="' +
            F.esc(x.code) + " · " + F.esc(x.kind) + " · 使用 " + F.pct(x.util, 0) + '">' +
            '<b>' + F.esc(x.code.split("-").slice(1).join("-")) + "</b>" +
            '<span>' + F.qty(x.stockQty) + "</span></div>";
        }).join("") + "</div></div></div>";

        html += '<div class="panel"><div class="panel-title">货位明细</div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "货位", render: function (r) { return '<span class="mono">' + F.esc(r.code) + "</span>"; } },
            { label: "库区", render: function (r) { return F.esc(r.zone); } },
            { label: "类型", render: function (r) { return F.tag(r.kind, "gray"); } },
            { label: "排-列-层", render: function (r) {
              return '<span class="mono small">' + r.aisle + "-" + r.col + "-" + r.level + "</span>";
            } },
            { label: "SKU / 数量", num: true, render: function (r) {
              return r.skuCount + " / " + F.qty(r.stockQty);
            } },
            { label: "容量", num: true, render: function (r) {
              return F.cube(r.used) + " / " + F.cube(r.capacity);
            } },
            { label: "利用率", render: function (r) {
              return '<div class="util-cell">' + F.progress(r.util) + '<span class="small">' +
                F.pct(r.util, 0) + "</span></div>";
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], shown, { click: function (r) { return r.code; }, empty: "该库区暂无货位" }) +
          "</div></div>";
        document.getElementById("view").innerHTML = html;

        document.querySelectorAll("[data-zone]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("locations", { zone: b.getAttribute("data-zone") });
          });
        });
        document.querySelectorAll("[data-z]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("locations", { zone: b.getAttribute("data-z") });
          });
        });
        F.bindRows(document, function (code) { showLoc(code, list); });
        document.querySelectorAll("[data-loc]").forEach(function (c) {
          c.addEventListener("click", function () { showLoc(c.getAttribute("data-loc"), list); });
        });

        F.setSide('<div class="side-block"><div class="hd">货位编码规则</div><div class="bd small" ' +
          'style="line-height:1.9">区-排-列-层，例如 <span class="mono">A-01-02-3</span>：A 区 1 排 ' +
          '2 列第 3 层。拣货按区 → 排 → 列（奇偶反向）→ 低层优先的蛇形顺序，减少行走距离。</div></div>');
        F.setStatus("库位管理 · " + list.length + " 个货位");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function showLoc(code, list) {
      var l = (list || []).filter(function (x) { return x.code === code; })[0] || {};
      F.api("GET", "/api/stock?location=" + encodeURIComponent(code)).then(function (d) {
        var html = '<div class="kv-grid">' +
          F.kv("货位", '<span class="mono">' + F.esc(code) + "</span>") +
          F.kv("类型", F.esc(l.kind || "")) +
          F.kv("容量", F.cube(l.capacity || 0)) +
          F.kv("已用", F.cube(l.used || 0) + "（" + F.pct(l.util || 0, 0) + "）") +
          F.kv("SKU 数", (d.summary || {}).sku || 0) +
          F.kv("状态", F.tag(l.status || "空闲")) + "</div>" +
          (d.list && d.list.length ? F.table([
            { label: "物料", render: function (r) { return F.esc(r.item) + " " +
              '<span class="muted small">' + F.esc(r.name) + "</span>"; } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "可用", num: true, render: function (r) { return F.qty(r.avail); } },
            { label: "有效期", render: function (r) { return F.esc(r.expiry || "—"); } }
          ], d.list) : F.empty("该货位为空"));
        F.dialog("货位 " + code, html, '<button class="btn" data-close-foot="1">关闭</button>');
        document.querySelector("[data-close-foot]").addEventListener("click", F.closeDialog);
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });

  /* ============================================================ 补货与移库 */
  F.register("replenish", function () {
    function load() {
      Promise.all([
        F.api("GET", "/api/replenish"),
        F.api("GET", "/api/transfers")
      ]).then(function (res) {
        var d = res[0], t = res[1];
        var sug = d.suggestions || [];
        var tasks = d.tasks || [];
        var html = '<div class="panel"><div class="panel-title">补货与移库' +
          '<span class="panel-actions small muted">拣货面下限 ' + d.min + " 件 / 上限 " +
          d.max + " 件</span></div><div class=\"panel-body\"><div class=\"kpi-grid four\">" +
          '<div class="kpi"><div class="k-label">补货建议</div><div class="k-value">' + sug.length +
          '</div><div class="k-sub">缺货 ' + sug.filter(function (x) { return x.urgent; }).length +
          " 个拣货面</div></div>" +
          '<div class="kpi gold"><div class="k-label">待执行任务</div><div class="k-value">' +
          tasks.filter(function (x) { return x.status === "待执行"; }).length +
          '</div><div class="k-sub">已完成 ' + tasks.filter(function (x) {
            return x.status === "已完成";
          }).length + "</div></div>" +
          '<div class="kpi green"><div class="k-label">移库记录</div><div class="k-value">' +
          (t.list || []).length + '</div><div class="k-sub">库内调拨</div></div>' +
          '<div class="kpi"><div class="k-label">补货策略</div><div class="k-value">' +
          (d.min > 0 ? "双箱制" : "—") + '</div><div class="k-sub">低于下限补至上限与需求较大者</div></div>' +
          "</div></div></div>";

        html += '<div class="panel"><div class="panel-title">补货建议' +
          '<span class="panel-actions"><button class="btn sm" id="rpGen">按建议生成任务</button></span></div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "物料", render: function (r) { return '<b class="small">' + F.esc(r.item) + "</b>" +
              '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
            { label: "拣货面", num: true, render: function (r) { return F.qty(r.pickface); } },
            { label: "待出需求", num: true, render: function (r) { return F.qty(r.demand); } },
            { label: "建议补货", num: true, render: function (r) { return '<b>' + F.qty(r.qty) + "</b>"; } },
            { label: "来源货位", render: function (r) { return '<span class="mono small">' +
              F.esc(r.storage || "—") + "</span>"; } },
            { label: "目标货位", render: function (r) { return '<span class="mono small">' +
              F.esc(r.pickLoc || "—") + "</span>"; } },
            { label: "紧急", render: function (r) { return r.urgent ? F.tag("断货", "red") :
              F.tag("常规", "gray"); } },
            { label: "", render: function (r) {
              return '<button class="btn sm" data-rp="' + F.esc(r.item) + '" data-qty="' +
                r.qty + '">生成任务</button>';
            } }
          ], sug, { empty: "拣货面库存充足，无需补货" }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">补货任务</div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "任务号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "物料", render: function (r) { return F.esc(r.item) + " " +
              '<span class="muted small">' + F.esc(r.name) + "</span>"; } },
            { label: "从 → 到", render: function (r) { return '<span class="mono small">' +
              F.esc(r.from_loc) + " → " + F.esc(r.to_loc) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "", render: function (r) {
              return r.status === "待执行" ? '<button class="btn sm primary" data-rpd="' +
                F.esc(r.no) + '">执行补货</button>' : '<span class="small muted">' +
                F.esc(r.done_at || "") + "</span>";
            } }
          ], tasks, { empty: "暂无补货任务" }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">库内移库' +
          '<span class="panel-actions"><button class="btn sm" id="mvNew">新建移库</button></span></div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "物料", render: function (r) { return F.esc(r.item); } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "从 → 到", render: function (r) { return '<span class="mono small">' +
              F.esc(r.from_loc) + " → " + F.esc(r.to_loc) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "操作人", render: function (r) { return F.esc(r.operator); } },
            { label: "时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.created_at) + "</span>"; } }
          ], t.list, { empty: "暂无移库记录" }) + "</div></div>";

        document.getElementById("view").innerHTML = html;

        document.getElementById("rpGen").addEventListener("click", function () {
          if (!sug.length) { F.toast("当前没有补货建议", "err"); return; }
          var seq = Promise.resolve(), n = 0;
          sug.slice(0, 10).forEach(function (x) {
            seq = seq.then(function () {
              return F.api("POST", "/api/replenish", { item: x.item, qty: x.qty, to: x.pickLoc })
                .then(function () { n += 1; }).catch(function () {});
            });
          });
          seq.then(function () {
            F.toast("已生成 " + n + " 条补货任务", "ok");
            load(); F.boot();
          });
        });
        document.querySelectorAll("[data-rp]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.api("POST", "/api/replenish", {
              item: b.getAttribute("data-rp"), qty: Number(b.getAttribute("data-qty"))
            }).then(function (x) {
              F.toast("已生成补货任务 " + x.no, "ok"); load(); F.boot();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
        document.querySelectorAll("[data-rpd]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.api("POST", "/api/replenish/" + b.getAttribute("data-rpd") + "/done", {})
              .then(function (x) {
                F.toast("补货完成 " + F.qty(x.qty) + " 件", "ok"); load(); F.boot();
              }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
        document.getElementById("mvNew").addEventListener("click", function () {
          F.api("GET", "/api/locations?limit=400").then(function (l) {
            F.dialog("新建移库",
              '<div class="form-grid">' +
              '<label>物料<input id="mvItem" placeholder="如 SKU-1021"></label>' +
              '<label>源货位<select id="mvFrom">' + (l.list || []).filter(function (x) {
                return x.stockQty > 0;
              }).map(function (x) {
                return '<option value="' + F.esc(x.code) + '">' + F.esc(x.code) + " · " +
                  F.qty(x.stockQty) + " 件</option>";
              }).join("") + "</select></label>" +
              '<label>目标货位<select id="mvTo">' + (l.list || []).map(function (x) {
                return '<option value="' + F.esc(x.code) + '">' + F.esc(x.code) + " · " +
                  F.esc(x.kind) + "</option>";
              }).join("") + "</select></label>" +
              '<label>数量<input id="mvQty" type="number" value="10"></label></div>',
              '<button class="btn primary" id="mvOk">确认移库</button>');
            document.getElementById("mvOk").addEventListener("click", function () {
              F.api("POST", "/api/transfers", {
                item: document.getElementById("mvItem").value.trim(),
                from: document.getElementById("mvFrom").value,
                to: document.getElementById("mvTo").value,
                qty: Number(document.getElementById("mvQty").value || 0)
              }).then(function (x) {
                F.closeDialog(); F.toast("移库完成 " + x.no, "ok"); load();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          }).catch(function (e) { F.toast(e.message, "err"); });
        });

        F.setSide('<div class="side-block"><div class="hd">补货口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">补货量 = max(上限, 待出需求) − 当前拣货面数量；' +
          '拣货面低于下限或低于待出库需求即触发。移库与补货都会写库存流水，可在批次追溯里看到。</div></div>');
        F.setStatus("补货移库 · " + sug.length + " 条建议");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });
})(window, document);
