/* 飞传 WMS · 报表分析与集成中心 */
(function (window, document) {
  "use strict";
  var F = window.F;

  /* ============================================================ 报表分析 */
  F.register("reports", function (params) {
    var days = Number(params.days || 14);

    function load() {
      F.api("GET", "/api/reports?days=" + days).then(function (d) {
        var k = d.kpi;
        var html = '<div class="panel"><div class="panel-title">报表分析' +
          '<span class="panel-actions">' +
          F.chips([[7, "7 天"], [14, "14 天"], [30, "30 天"], [90, "90 天"]].map(function (x) {
            return [String(x[0]), x[1]];
          }), String(days), "data-days") +
          '<a class="btn sm" href="api/export/orders.csv" target="_blank">导出出库单</a>' +
          "</span></div><div class=\"panel-body\"><div class=\"kpi-grid six\">" +
          '<div class="kpi"><div class="k-label">入库量</div><div class="k-value">' +
          F.wan(k.inbound) + '</div><div class="k-sub">近 ' + d.days + " 天累计（件）</div></div>" +
          '<div class="kpi green"><div class="k-label">出库量</div><div class="k-value">' +
          F.wan(k.outbound) + '</div><div class="k-sub">拣货 ' + k.pickLines + " 行</div></div>" +
          '<div class="kpi"><div class="k-label">出库单 / 发运</div><div class="k-value">' +
          k.orders + " / " + k.shipments + '</div><div class="k-sub">按创建与发运时间</div></div>' +
          '<div class="kpi green"><div class="k-label">准时发运率</div><div class="k-value">' +
          F.pct(k.onTimeRate, 1) + '</div><div class="k-sub">目标 98%</div></div>' +
          '<div class="kpi gold"><div class="k-label">盘点准确率</div><div class="k-value">' +
          F.pct(k.accuracy, 2) + '</div><div class="k-sub">按行完全一致计</div></div>' +
          '<div class="kpi"><div class="k-label">月周转 / 库容</div><div class="k-value">' +
          F.num(k.turnover, 2) + " / " + F.pct(k.locUtil, 0) +
          '</div><div class="k-sub">人均 ' + F.num(k.productivity, 1) + " 行/小时</div></div></div></div></div>";

        html += '<div class="panel"><div class="panel-title">出入库趋势</div><div class="panel-body">' +
          F.lineChart([
            { name: "入库", data: (d.trend || []).map(function (t) { return t.inbound; }) },
            { name: "出库", data: (d.trend || []).map(function (t) { return t.outbound; }) }
          ], { labels: (d.trend || []).map(function (t) { return t.day; }),
            colors: ["#1f7a8c", "#c8963e"] }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">承运商绩效</div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "承运商", render: function (r) { return '<b>' + F.esc(r.name) + "</b>" +
              ' <span class="muted small mono">' + F.esc(r.code) + "</span>"; } },
            { label: "发运单量", num: true, render: function (r) { return r.count; } },
            { label: "重量", num: true, render: function (r) { return F.num(r.weight, 0) + " kg"; } },
            { label: "运费", num: true, render: function (r) { return F.num(r.cost, 0); } },
            { label: "准时率", render: function (r) {
              return '<div class="util-cell">' + F.progress(r.onTime) + '<span class="small">' +
                F.pct(r.onTime, 1) + "</span></div>";
            } }
          ], d.carriers, { empty: "暂无发运记录" }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">客户出库金额 TOP</div><div class="panel-body">' +
          (d.customers || []).length ? F.barChart((d.customers || []).map(function (c) {
            return { label: c.name.slice(0, 6), label2: F.wan(c.amount), value: c.amount };
          }), { height: 190 }) : F.empty("暂无数据") + "</div></div>";

        html += '<div class="panel"><div class="panel-title">物料消耗 TOP10</div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "物料", render: function (r) { return '<b class="small">' + F.esc(r.item) +
              '</b><div class="muted small">' + F.esc(r.name) + "</div>"; } },
            { label: "出库数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "占比", render: function (r) {
              var tot = (d.consume || []).reduce(function (a, x) { return a + x.qty; }, 0) || 1;
              return '<div class="util-cell">' + F.progress(r.qty / tot) +
                '<span class="small">' + F.pct(r.qty / tot, 1) + "</span></div>";
            } }
          ], d.consume, { empty: "暂无出库" }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">作业人员绩效</div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "操作人", render: function (r) { return F.esc(r.operator); } },
            { label: "作业次数", num: true, render: function (r) { return r.lines; } },
            { label: "作业数量", num: true, render: function (r) { return F.qty(r.qty); } }
          ], d.staff, { empty: "暂无记录" }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">库区负荷与 ABC</div><div class="panel-body">' +
          '<div class="kv-grid">' +
          ["A", "B", "C"].map(function (x) {
            var s = (d.abc || {})[x] || { count: 0, amount: 0, share: 0 };
            return F.kv(x + " 类物料", s.count + " 个 · " + F.wan(s.amount) + "（" +
              F.pct(s.share, 0) + "）");
          }).join("") +
          F.kv("已过期批次", (d.expiry || {})["已过期"] || 0) +
          F.kv("临期批次", (d.expiry || {})["临期"] || 0) +
          F.kv("关注批次", (d.expiry || {})["关注"] || 0) +
          "</div>" + (d.zones || []).map(function (z) {
            return '<div class="bar-row"><span class="bar-name">' + F.esc(z.code) + " " +
              F.esc(z.kind) + "</span>" + F.progress(z.util) +
              '<span class="bar-val">' + F.pct(z.util, 0) + "</span></div>";
          }).join("") + "</div></div>";

        document.getElementById("view").innerHTML = html;

        document.querySelectorAll("[data-days]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("reports", { days: b.getAttribute("data-days") });
          });
        });

        F.setSide('<div class="side-block"><div class="hd">指标口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">· 入库量：上架 + 收货流水<br>' +
          '· 出库量：拣货出库流水<br>' +
          '· 准时发运：发运时间早于承运商截单时间<br>' +
          '· 盘点准确率：账面与实盘完全一致的货位行占比<br>' +
          '· 月周转：近 30 天出库成本 ÷ 当前库存成本</div></div>');
        F.setStatus("报表分析 · 近 " + d.days + " 天");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });

  /* ============================================================ 集成中心 */
  F.register("integration", function (params) {
    var tab = params.tab || "overview";
    if (!F.isAdmin()) {
      document.getElementById("view").innerHTML = '<div class="panel"><div class="panel-title">' +
        "集成中心</div><div class='panel-body'><div class='empty-hint'>集成配置仅系统管理员可见。" +
        "当前角色：" + F.esc(F.me().roleLabel) + "</div></div></div>";
      return;
    }

    function load() {
      Promise.all([
        F.api("GET", "/api/integration/overview"),
        F.api("GET", "/api/integration/keys"),
        F.api("GET", "/api/integration/webhooks"),
        F.api("GET", "/api/integration/deliveries?limit=40"),
        F.api("GET", "/api/integration/mappings")
      ]).then(function (res) {
        var ov = res[0], keys = res[1].list || [], hooks = res[2].list || [];
        var deliv = res[3].list || [], maps = res[4].list || [];

        var html = '<div class="panel"><div class="panel-title">集成中心' +
          '<span class="panel-actions small muted">与 ERP / MES / TMS 对接</span></div>' +
          '<div class="panel-body"><div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">API Key</div><div class="k-value">' +
          ov.keys.enabled + " / " + ov.keys.total + '</div><div class="k-sub">累计调用 ' +
          ov.keys.calls + " 次</div></div>" +
          '<div class="kpi green"><div class="k-label">Webhook</div><div class="k-value">' +
          ov.webhooks.enabled + " / " + ov.webhooks.total + '</div><div class="k-sub">成功 ' +
          (ov.deliveries["成功"] || 0) + " · 失败 " + (ov.deliveries["失败"] || 0) + "</div></div>" +
          '<div class="kpi"><div class="k-label">变更事件</div><div class="k-value">' +
          ov.changes + '</div><div class="k-sub">最近 ' + F.esc((ov.lastChange || "—").slice(5)) +
          "</div></div>" +
          '<div class="kpi gold"><div class="k-label">外部映射</div><div class="k-value">' +
          ov.mappings + '</div><div class="k-sub">系统间 ID 对照</div></div></div>' +
          F.chips([["overview", "集成总览"], ["keys", "API Key (" + keys.length + ")"],
            ["hooks", "Webhook (" + hooks.length + ")"],
            ["delivery", "投递记录 (" + deliv.length + ")"],
            ["mapping", "外部映射 (" + maps.length + ")"],
            ["sync", "增量同步"]], tab, "data-tab") + "</div></div>";

        html += '<div class="panel"><div class="panel-title">' +
          ({ overview: "接入说明", keys: "API Key", hooks: "Webhook 订阅", delivery: "投递记录",
            mapping: "外部 ID 映射", sync: "增量同步" }[tab] || "集成") +
          "</div><div class='panel-body' id='igBody'></div></div>";
        document.getElementById("view").innerHTML = html;
        var body = document.getElementById("igBody");

        if (tab === "overview") {
          body.innerHTML = '<div class="kv-grid">' +
            F.kv("鉴权方式", "Authorization: Bearer &lt;Key&gt; / X-Fc-Key") +
            F.kv("Key 前缀", '<span class="mono">fck_</span>') +
            F.kv("幂等", "POST 支持 Idempotency-Key 头") +
            F.kv("接口契约", '<a href="api/openapi.json" target="_blank">/api/openapi.json</a>') +
            F.kv("Webhook 签名", "HMAC-SHA256(secret, timestamp + '.' + body)") +
            F.kv("重试策略", "30 / 60 / 120 秒，最多 3 次") +
            F.kv("增量同步", "GET /api/sync/changes?since=&lt;游标&gt;") +
            F.kv("事件清单", (ov.events || []).length + " 类") +
            "</div>" +
            '<div class="sub-title">订阅事件</div><div class="event-tags">' +
            (ov.events || []).map(function (e) {
              return '<span class="tag blue mono">' + F.esc(e) + "</span>";
            }).join("") + "</div>" +
            '<div class="sub-title">对接建议</div>' +
            '<div class="small muted" style="line-height:2">' +
            "1. ERP 采购入库：先建 ASN（POST /api/asns），到货后逐行收货，质检合格再上架；<br>" +
            "2. ERP 销售出库：POST /api/orders 建单 → POST /api/orders/{no}/alloc 分配 → " +
            "波次拣货 → 打包 → 发运；<br>" +
            "3. MES 领料：以 order.type=生产领料 建单，出库后通过 order.shipped 事件回传；<br>" +
            "4. TMS 交接：订阅 order.shipped 拿到运单号与箱数，回写签收时调用 " +
            "POST /api/orders/{no}/stage {target:'已签收'}；<br>" +
            "5. 库存对账：每日 GET /api/stock/summary 与 ERP 账面比对，差异走 /api/moves 调整。" +
            "</div>" + '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn sm" id="igTest">发送测试事件</button></div>';
          document.getElementById("igTest").addEventListener("click", function () {
            F.api("POST", "/api/integration/test", { event: "test.ping" }).then(function (x) {
              F.toast("已排队 " + x.queued + " 条投递", "ok");
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        } else if (tab === "keys") {
          body.innerHTML = '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn primary" id="ikNew">生成 API Key</button></div>' +
            F.table([
              { label: "名称", render: function (r) { return '<b>' + F.esc(r.name) + "</b>"; } },
              { label: "前缀", render: function (r) { return '<span class="mono">' + F.esc(r.prefix) + "…</span>"; } },
              { label: "权限", render: function (r) { return F.tag(r.scope === "write" ? "读写" : "只读",
                r.scope === "write" ? "gold" : "gray"); } },
              { label: "调用次数", num: true, render: function (r) { return r.calls; } },
              { label: "最近调用", render: function (r) { return '<span class="small muted">' +
                F.esc(r.lastUsedAt || "—") + "</span>"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "创建", render: function (r) { return '<span class="small muted">' +
                F.esc(r.createdAt) + "</span>"; } },
              { label: "", render: function (r) {
                return r.status === "启用" ? '<button class="btn sm danger" data-rk="' + r.id +
                  '">吊销</button>' : "";
              } }
            ], keys, { empty: "尚未创建 Key" });
          document.getElementById("ikNew").addEventListener("click", function () {
            F.dialog("生成 API Key",
              '<div class="form-grid">' +
              '<label>名称<input id="ikName" placeholder="如 ERP-PROD"></label>' +
              '<label>权限<select id="ikScope"><option value="read">只读</option>' +
              '<option value="write">读写</option></select></label></div>' +
              '<div class="muted small">密钥仅在生成时显示一次，请立即保存到对接系统的配置里。</div>',
              '<button class="btn primary" id="ikOk">生成</button>');
            document.getElementById("ikOk").addEventListener("click", function () {
              F.api("POST", "/api/integration/keys", {
                name: document.getElementById("ikName").value.trim(),
                scope: document.getElementById("ikScope").value
              }).then(function (x) {
                F.dialog("API Key 已生成",
                  '<div class="kv-grid">' + F.kv("名称", F.esc(x.name)) +
                  F.kv("权限", x.scope === "write" ? "读写" : "只读") + "</div>" +
                  '<div class="secret-box mono" id="ikVal">' + F.esc(x.key) + "</div>" +
                  '<div class="muted small">请立即保存，关闭后无法再次查看。</div>',
                  '<button class="btn" id="ikCopy">复制</button>' +
                  '<button class="btn primary" id="ikDone">我已保存</button>');
                document.getElementById("ikCopy").addEventListener("click", function () {
                  var t = document.getElementById("ikVal").textContent;
                  if (navigator.clipboard) navigator.clipboard.writeText(t);
                  F.toast("已复制到剪贴板", "ok");
                });
                document.getElementById("ikDone").addEventListener("click", function () {
                  F.closeDialog(); F.go("integration", { tab: "keys" });
                });
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          body.querySelectorAll("[data-rk]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("DELETE", "/api/integration/keys/" + b.getAttribute("data-rk"), {})
                .then(function () {
                  F.toast("Key 已吊销", "ok"); F.go("integration", { tab: "keys" });
                }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
        } else if (tab === "hooks") {
          body.innerHTML = '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn primary" id="ihNew">新建 Webhook</button></div>' +
            F.table([
              { label: "名称", render: function (r) { return '<b>' + F.esc(r.name) + "</b>"; } },
              { label: "回调地址", render: function (r) { return '<span class="mono small">' +
                F.esc(r.url) + "</span>"; } },
              { label: "订阅事件", render: function (r) { return F.esc(r.events) === "*" ?
                '<span class="tag gray">全部</span>' : r.events.split(",").map(function (e) {
                  return '<span class="tag blue mono">' + F.esc(e) + "</span>";
                }).join(" "); } },
              { label: "成功/失败", num: true, render: function (r) { return '<span class="green">' +
                r.delivered + '</span> / <span class="red">' + r.failed + "</span>"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "", render: function (r) {
                return '<button class="btn sm" data-ht="' + r.id + '">测试</button> ' +
                  '<button class="btn sm" data-he="' + r.id + '">编辑</button> ' +
                  '<button class="btn sm danger" data-hd="' + r.id + '">删除</button>';
              } }
            ], hooks, { empty: "尚未配置 Webhook" });
          document.getElementById("ihNew").addEventListener("click", hookForm);
          body.querySelectorAll("[data-ht]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("POST", "/api/integration/test", { event: "test.ping" }).then(function (x) {
                F.toast("测试事件已排队，共 " + x.queued + " 条待投递", "ok");
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          body.querySelectorAll("[data-he]").forEach(function (b) {
            b.addEventListener("click", function () {
              var h = hooks.filter(function (x) { return String(x.id) === b.getAttribute("data-he"); })[0];
              hookForm(h);
            });
          });
          body.querySelectorAll("[data-hd]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("DELETE", "/api/integration/webhooks/" + b.getAttribute("data-hd"), {})
                .then(function () {
                  F.toast("已删除", "ok"); F.go("integration", { tab: "hooks" });
                }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
        } else if (tab === "delivery") {
          body.innerHTML = F.table([
            { label: "ID", render: function (r) { return "#" + r.id; } },
            { label: "事件", render: function (r) { return '<span class="mono small">' +
              F.esc(r.event) + "</span>"; } },
            { label: "目标", render: function (r) { return '<span class="small">' +
              F.esc(r.name || "已删除") + "</span>"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "次数", num: true, render: function (r) { return r.try_no; } },
            { label: "HTTP", num: true, render: function (r) { return r.code || "—"; } },
            { label: "响应", render: function (r) { return '<span class="small muted">' +
              F.esc((r.resp || "").slice(0, 40)) + "</span>"; } },
            { label: "时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.created_at) + "</span>"; } },
            { label: "", render: function (r) {
              return r.status === "成功" ? "" : '<button class="btn sm" data-rt="' + r.id +
                '">重投</button>';
            } }
          ], deliv, { empty: "暂无投递记录" });
          body.querySelectorAll("[data-rt]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("POST", "/api/integration/deliveries/" + b.getAttribute("data-rt") + "/retry", {})
                .then(function () {
                  F.toast("已重新排队", "ok"); F.go("integration", { tab: "delivery" });
                }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
        } else if (tab === "mapping") {
          body.innerHTML = '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn primary" id="imNew">新增映射</button>' +
            '<button class="btn sm" id="imResolve">反查</button></div>' +
            F.table([
              { label: "外部系统", render: function (r) { return F.tag(r.system, "blue"); } },
              { label: "对象类型", render: function (r) { return F.esc(r.obj_type); } },
              { label: "外部 ID", render: function (r) { return '<span class="mono small">' +
                F.esc(r.ext_id) + "</span>"; } },
              { label: "本地 ID", render: function (r) { return '<span class="mono small">' +
                F.esc(r.local_id) + "</span>"; } },
              { label: "创建", render: function (r) { return '<span class="small muted">' +
                F.esc(r.created_at) + "</span>"; } }
            ], maps, { empty: "暂无映射（如 ERP 物料号 ↔ WMS 物料编码）" });
          document.getElementById("imNew").addEventListener("click", function () {
            F.dialog("新增外部 ID 映射",
              '<div class="form-grid">' +
              '<label>外部系统<input id="imSys" placeholder="ERP / MES / TMS"></label>' +
              '<label>对象类型<input id="imType" placeholder="item / order / asn"></label>' +
              '<label>外部 ID<input id="imExt" placeholder="ERP 侧主键"></label>' +
              '<label>本地 ID<input id="imLocal" placeholder="WMS 单据号或编码"></label></div>',
              '<button class="btn primary" id="imOk">保存</button>');
            document.getElementById("imOk").addEventListener("click", function () {
              F.api("POST", "/api/integration/mappings", {
                system: document.getElementById("imSys").value.trim(),
                objType: document.getElementById("imType").value.trim(),
                extId: document.getElementById("imExt").value.trim(),
                localId: document.getElementById("imLocal").value.trim()
              }).then(function () {
                F.closeDialog(); F.toast("映射已保存", "ok");
                F.go("integration", { tab: "mapping" });
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          document.getElementById("imResolve").addEventListener("click", function () {
            F.dialog("按 ID 反查",
              '<div class="form-grid">' +
              '<label>外部系统<input id="rvSys" value="ERP"></label>' +
              '<label>对象类型<input id="rvType" value="item"></label>' +
              '<label>外部 ID<input id="rvExt"></label></div>',
              '<button class="btn primary" id="rvOk">查询</button>');
            document.getElementById("rvOk").addEventListener("click", function () {
              F.api("POST", "/api/integration/resolve", {
                system: document.getElementById("rvSys").value.trim(),
                objType: document.getElementById("rvType").value.trim(),
                extId: document.getElementById("rvExt").value.trim()
              }).then(function (x) {
                F.toast(x.found ? "对应本地 ID：" + x.localId : "未找到映射",
                  x.found ? "ok" : "err");
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
        } else {
          body.innerHTML = '<div class="form-foot" style="justify-content:flex-start">' +
            '<input class="inp sm" id="sySince" placeholder="游标（留空从 0 开始）" value="0">' +
            '<button class="btn sm primary" id="syGo">拉取变更</button></div>' +
            '<div id="syOut" class="small"></div>' +
            '<div class="muted small" style="margin-top:10px">游标即 change_log 自增 ID，' +
            '轮询时把上次返回的 cursor 传回 since 即可，最多 500 条/次。</div>';
          document.getElementById("syGo").addEventListener("click", function () {
            var since = document.getElementById("sySince").value.trim() || "0";
            F.api("GET", "/api/sync/changes?since=" + encodeURIComponent(since) + "&limit=20")
              .then(function (x) {
                document.getElementById("syOut").innerHTML =
                  '<div class="mono small" style="line-height:1.8">cursor=' + x.cursor +
                  " · count=" + x.count + " · hasMore=" + x.hasMore + "</div>" +
                  F.table([
                    { label: "ID", render: function (r) { return r.id; } },
                    { label: "对象", render: function (r) { return F.tag(r.object, "gray"); } },
                    { label: "对象 ID", render: function (r) { return '<span class="mono small">' +
                      F.esc(r.object_id) + "</span>"; } },
                    { label: "变更时间", render: function (r) { return '<span class="small muted">' +
                      F.esc(r.changed_at) + "</span>"; } },
                    { label: "载荷", render: function (r) { return '<span class="mono small">' +
                      F.esc(JSON.stringify(r.payloadObj).slice(0, 80)) + "</span>"; } }
                  ], x.list);
                document.getElementById("sySince").value = x.cursor;
              }).catch(function (e) { F.toast(e.message, "err"); });
          });
        }

        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("integration", { tab: b.getAttribute("data-tab") });
          });
        });
        F.setStatus("集成中心 · " + tab);
        F.setSide('<div class="side-block"><div class="hd">三通道</div><div class="bd small muted" ' +
          'style="line-height:1.9">① API Key：系统间调用，读写分离；<br>' +
          '② Webhook：事件推送，带 HMAC 签名与退避重试；<br>' +
          '③ 增量同步：游标拉取变更，适合弱实时对账。</div></div>');
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function hookForm(h) {
      F.dialog(h ? "编辑 Webhook" : "新建 Webhook",
        '<div class="form-grid">' +
        '<label>名称<input id="ihName" value="' + F.esc(h ? h.name : "") +
        '" placeholder="如 ERP 回调"></label>' +
        '<label>回调地址<input id="ihUrl" value="' + F.esc(h ? h.url : "") +
        '" placeholder="https://erp.example.com/hooks/wms"></label>' +
        '<label class="full">订阅事件（逗号分隔，* 为全部）<input id="ihEv" value="' +
        F.esc(h ? h.events : "*") + '"></label></div>' +
        (h ? '<div class="muted small">secret 已固定，如需更换请重建。</div>' :
          '<div class="muted small">创建后会显示一次 secret，用于校验 X-Fc-Signature。</div>'),
        '<button class="btn primary" id="ihOk">' + (h ? "保存" : "创建") + "</button>");
      document.getElementById("ihOk").addEventListener("click", function () {
        var payload = {
          name: document.getElementById("ihName").value.trim(),
          url: document.getElementById("ihUrl").value.trim(),
          events: document.getElementById("ihEv").value.trim() || "*"
        };
        var req = h ? F.api("PUT", "/api/integration/webhooks/" + h.id, payload)
          : F.api("POST", "/api/integration/webhooks", payload);
        req.then(function (x) {
          if (!h && x.secret) {
            F.dialog("Webhook 已创建",
              '<div class="kv-grid">' + F.kv("名称", F.esc(x.name)) + "</div>" +
              '<div class="muted small">签名密钥（用于校验 X-Fc-Signature）：</div>' +
              '<div class="secret-box mono">' + F.esc(x.secret) + "</div>" +
              '<div class="muted small">签名算法：HMAC-SHA256(secret, timestamp + "." + body)</div>',
              '<button class="btn primary" id="ihDone">我已保存</button>');
            document.getElementById("ihDone").addEventListener("click", function () {
              F.closeDialog(); F.go("integration", { tab: "hooks" });
            });
          } else {
            F.closeDialog(); F.toast("已保存", "ok");
            F.go("integration", { tab: "hooks" });
          }
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }
    load();
  });
})(window, document);
