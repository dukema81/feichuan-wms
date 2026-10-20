/* 飞传 WMS · 批次追溯与盘点作业 */
(function (window, document) {
  "use strict";
  var F = window.F;

  /* ============================================================ 批次追溯 */
  F.register("trace", function (params) {
    var lot = params.lot || "";
    var order = params.order || "";

    function load() {
      Promise.all([
        lot || order ? F.api("GET", "/api/trace?" + (lot ? "lot=" + encodeURIComponent(lot)
          : "order=" + encodeURIComponent(order))) : Promise.resolve(null),
        F.api("GET", "/api/moves?limit=12"),
        F.api("GET", "/api/lots?limit=12" + (lot ? "&q=" + encodeURIComponent(lot.slice(0, 6)) : ""))
      ]).then(function (res) {
        var t = res[0], mv = res[1], ls = res[2];
        var html = '<div class="panel"><div class="panel-title">批次追溯' +
          '<span class="panel-actions">' +
          '<input class="inp sm" id="trQ" placeholder="输入批次号或出库单号" value="' +
          F.esc(lot || order) + '" style="width:230px">' +
          '<button class="btn sm primary" id="trGo">追溯</button></span></div>' +
          '<div class="panel-body">' +
          '<div class="muted small">支持正向（批次 → 客户）与反向（订单 → 批次）追溯，' +
          '数据来自收货、上架、拣货、移库、盘点全量流水。</div></div></div>';

        if (t) {
          if (t.lots) {
            html += '<div class="panel"><div class="panel-title">出库单 ' + F.esc(t.order) +
              ' 关联批次</div><div class="panel-body">' + t.lots.map(function (x) {
                return '<div class="trace-chip" data-lot="' + F.esc(x.lot) + '"><b>' +
                  F.esc(x.lot) + "</b> " + F.esc(x.name) + " · " + F.qty(x.qty) +
                  " 件 → " + F.esc((x.customers || []).join("、") || "—") + "</div>";
              }).join("") + "</div></div>";
          } else {
            var chain = '<div class="trace-chain">';
            chain += '<div class="tc-col"><div class="tc-hd">入库来源</div>' +
              (t.inbound.length ? t.inbound.map(function (x) {
                return '<div class="tc-card"><b>' + F.esc(x.supplierName || "未知供应商") + "</b>" +
                  '<div class="mono small">' + F.esc(x.asn) + "</div>" +
                  '<div class="muted small">' + F.esc(x.ts) + " · " + F.qty(x.qty) + " 件</div></div>";
              }).join("") : '<div class="tc-card muted">无入库记录</div>') + "</div>";
            chain += '<div class="tc-arrow">→</div>';
            chain += '<div class="tc-col"><div class="tc-hd">当前在库（' + t.stocks.length + " 个货位）</div>" +
              (t.stocks.length ? t.stocks.map(function (x) {
                return '<div class="tc-card"><b class="mono">' + F.esc(x.location) + "</b>" +
                  '<div class="small">' + F.qty(x.qty) + " 件 · 可用 " + F.qty(x.avail) + "</div>" +
                  '<div class="muted small">' + F.esc(x.status) + "</div></div>";
              }).join("") : '<div class="tc-card muted">已全部出库</div>') + "</div>";
            chain += '<div class="tc-arrow">→</div>';
            chain += '<div class="tc-col"><div class="tc-hd">出库去向（' + t.outbound.length + " 单）</div>" +
              (t.outbound.length ? t.outbound.map(function (x) {
                return '<div class="tc-card"><b>' + F.esc(x.customerName || "—") + "</b>" +
                  '<div class="mono small">' + F.esc(x.order) + "</div>" +
                  '<div class="muted small">' + F.esc(x.ts) + " · " + F.qty(x.qty) + " 件" +
                  (x.trackingNo ? " · " + F.esc(x.trackingNo) : "") + "</div></div>";
              }).join("") : '<div class="tc-card muted">尚未出库</div>') + "</div>";
            chain += "</div>";

            html += '<div class="panel"><div class="panel-title">批次 ' + F.esc(t.lot) +
              ' · ' + F.esc(t.name) + '<span class="panel-actions">' + F.tag(t.expiryLevel) +
              "</span></div><div class='panel-body'>" +
              '<div class="kpi-grid four">' +
              '<div class="kpi"><div class="k-label">当前在库</div><div class="k-value">' +
              F.qty(t.qty) + '</div><div class="k-sub">累计入库 ' + F.qty(t.qtyIn) +
              " · 已出 " + F.qty(t.outQty) + "</div></div>" +
              '<div class="kpi green"><div class="k-label">货值</div><div class="k-value">' +
              F.wan(t.qty * t.price) + '</div><div class="k-sub">单价 ' + F.num(t.price, 2) + "</div></div>" +
              '<div class="kpi ' + (t.expiryLevel === "临期" ? "gold" : (t.expiryLevel === "已过期" ?
                "red" : "")) + '"><div class="k-label">剩余保质期</div><div class="k-value">' +
              (t.daysLeft === null ? "—" : t.daysLeft + " 天") +
              '</div><div class="k-sub">有效期 ' + F.esc(t.expiry || "—") + "</div></div>" +
              '<div class="kpi"><div class="k-label">物料</div><div class="k-value" style="font-size:15px">' +
              F.esc(t.item) + '</div><div class="k-sub">' + F.esc(t.abc) + " 类 · " +
              F.esc(t.storage) + "</div></div></div>" +
              '<div class="kv-grid">' +
              F.kv("供应商", F.esc(t.supplier || "—")) +
              F.kv("入库时间", F.esc(t.inboundAt || "—")) +
              F.kv("生产日期", F.esc(t.mfgDate || "—")) +
              F.kv("涉及客户", (t.customers || []).length ? F.esc(t.customers.join("、")) : "—") +
              "</div>" + chain + "</div></div>";

            html += '<div class="panel"><div class="panel-title">库存流水（' + t.moves.length +
              " 条）</div><div class='panel-body flush'>" + F.table([
                { label: "时间", render: function (r) { return '<span class="mono small">' +
                  F.esc(r.ts) + "</span>"; } },
                { label: "类型", render: function (r) { return F.tag(r.type, r.type === "拣货出库" ?
                  "gold" : (r.type === "上架" ? "green" : "blue")); } },
                { label: "从 → 到", render: function (r) { return '<span class="mono small">' +
                  F.esc(r.from_loc || "—") + " → " + F.esc(r.to_loc || "—") + "</span>"; } },
                { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
                { label: "关联单据", render: function (r) { return '<span class="mono small">' +
                  F.esc(r.ref_no || "—") + "</span>"; } },
                { label: "操作人", render: function (r) { return F.esc(r.operator); } }
              ], t.moves) + "</div></div>";

            if ((t.related || []).length) {
              html += '<div class="panel"><div class="panel-title">同物料其他批次</div>' +
                '<div class="panel-body">' + t.related.map(function (x) {
                  return '<div class="trace-chip" data-lot="' + F.esc(x.lot) + '"><b>' +
                    F.esc(x.lot) + "</b> 效期 " + F.esc(x.expiry || "—") + " · 在库 " +
                    F.qty(x.qty) + " 件</div>";
                }).join("") + "</div></div>";
            }
          }
        }

        html += '<div class="panel"><div class="panel-title">最近批次</div><div class="panel-body">' +
          (ls.list || []).map(function (x) {
            return '<div class="trace-chip" data-lot="' + F.esc(x.lot) + '"><b>' + F.esc(x.lot) +
              "</b> " + F.esc(x.name) + " · 在库 " + F.qty(x.qty) + " 件 · " +
              (x.expiry ? "效期 " + F.esc(x.expiry) : "无有效期") + "</div>";
          }).join("") + "</div></div>";

        html += '<div class="panel"><div class="panel-title">最近库存流水' +
          '<span class="panel-actions"><a class="btn sm" href="#stock">库存台账</a></span></div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "时间", render: function (r) { return '<span class="mono small">' +
              F.esc(r.ts) + "</span>"; } },
            { label: "类型", render: function (r) { return F.tag(r.type, "blue"); } },
            { label: "物料", render: function (r) { return F.esc(r.item) +
              '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
            { label: "批次", render: function (r) { return '<span class="mono small">' +
              F.esc(r.lot) + "</span>"; } },
            { label: "货位", render: function (r) { return '<span class="mono small">' +
              F.esc(r.from_loc || "—") + " → " + F.esc(r.to_loc || "—") + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "单据", render: function (r) { return F.esc(r.ref_no || "—"); } }
          ], mv.list) + "</div></div>";

        document.getElementById("view").innerHTML = html;
        document.getElementById("trGo").addEventListener("click", function () {
          var v = document.getElementById("trQ").value.trim();
          if (!v) return;
          if (/^SO/i.test(v)) F.go("trace", { order: v.toUpperCase() });
          else F.go("trace", { lot: v.toUpperCase() });
        });
        document.querySelectorAll("[data-lot]").forEach(function (c) {
          c.addEventListener("click", function () { F.go("trace", { lot: c.getAttribute("data-lot") }); });
        });
        F.setSide('<div class="side-block"><div class="hd">追溯口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">批次号在收货时生成或录入，贯穿上架、移库、拣货、盘点全流程；' +
          '出库分配按 FEFO 优先消耗近效期批次，因此同物料可能拆成多批次出库。</div></div>');
        F.setStatus("批次追溯 · " + (t ? (t.lot || ("订单 " + t.order)) : "未选择批次"));
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });

  /* ============================================================ 盘点作业 */
  F.register("stocktake", function (params) {
    var st = params.st || "全部";

    function load() {
      F.api("GET", "/api/stocktakes").then(function (d) {
        var c = d.counts || {};
        var list = d.list || [];
        var acc = 1;
        var html = '<div class="panel"><div class="panel-title">盘点作业' +
          '<span class="panel-actions"><button class="btn sm primary" id="stNew">发起盘点</button>' +
          '<button class="btn sm" id="stRefresh">刷新</button></span></div>' +
          '<div class="panel-body"><div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">盘点中</div><div class="k-value">' +
          ((c["盘点中"] || 0) + (c["草稿"] || 0)) +
          '</div><div class="k-sub">草稿 ' + (c["草稿"] || 0) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">待审核</div><div class="k-value">' +
          (c["待审核"] || 0) + '</div><div class="k-sub">差异需二审放行</div></div>' +
          '<div class="kpi green"><div class="k-label">已调整 / 关闭</div><div class="k-value">' +
          ((c["已调整"] || 0) + (c["已关闭"] || 0)) +
          '</div><div class="k-sub">差异已入账</div></div>' +
          '<div class="kpi"><div class="k-label">盘点单据</div><div class="k-value">' + d.total +
          '</div><div class="k-sub">明盘 / 盲盘</div></div></div>' +
          F.chips([["全部", "全部", d.total], ["盘点中", "盘点中", c["盘点中"] || 0],
            ["待审核", "待审核", c["待审核"] || 0], ["已调整", "已调整", c["已调整"] || 0]],
            st, "data-st") + "</div></div>";

        html += '<div class="panel"><div class="panel-title">盘点单</div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "单号", render: function (r) { return '<span class="mono">' + F.esc(r.no) + "</span>"; } },
            { label: "库区", render: function (r) { return F.esc(r.zone || "全仓"); } },
            { label: "方式", render: function (r) { return F.tag(r.type, r.type === "盲盘" ? "gold" : "gray"); } },
            { label: "行数", num: true, render: function (r) { return r.lineCount; } },
            { label: "差异", num: true, render: function (r) { return r.diffLines ?
              '<b class="red">' + r.diffLines + "</b> 行" : "—"; } },
            { label: "损益金额", num: true, render: function (r) {
              return r.diffAmount ? '<b class="' + (r.diffAmount < 0 ? "red" : "green") + '">' +
                F.num(r.diffAmount, 2) + "</b>" : "—";
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "创建", render: function (r) { return '<span class="small muted">' +
              F.esc(r.createdAt) + "</span>"; } }
          ], st === "全部" ? list : list.filter(function (x) { return x.status === st; }),
            { click: function (r) { return r.no; }, empty: "暂无盘点单" }) + "</div></div>";
        document.getElementById("view").innerHTML = html;

        F.bindRows(document, openSt);
        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("stocktake", { st: b.getAttribute("data-st") });
          });
        });
        document.getElementById("stNew").addEventListener("click", function () {
          F.dialog("发起盘点",
            '<div class="form-grid">' +
            '<label>盘点库区<select id="stZone"><option value="">全仓（所有库区）</option>' +
            (d.zones || []).map(function (x) {
              return '<option value="' + F.esc(x) + '">' + F.esc(x) + " 区</option>";
            }).join("") + "</select></label>" +
            '<label>盘点方式<select id="stType"><option>明盘</option><option>盲盘</option>' +
            "</select></label>" +
            '<label class="full">备注<input id="stNote" placeholder="如 月末循环盘点"></label></div>' +
            '<div class="muted small">明盘会带出账面数，盲盘只显示货位与物料，需实盘录入。</div>',
            '<button class="btn primary" id="stOk">发起</button>');
          document.getElementById("stOk").addEventListener("click", function () {
            F.api("POST", "/api/stocktakes", {
              zone: document.getElementById("stZone").value,
              type: document.getElementById("stType").value,
              note: document.getElementById("stNote").value.trim()
            }).then(function (x) {
              F.closeDialog();
              F.toast("盘点单 " + x.no + " 已创建，" + x.lines + " 行", "ok");
              F.go("stocktake", { st: "全部" }); F.boot();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
        document.getElementById("stRefresh").addEventListener("click", function () {
          F.go("stocktake", { st: st });
        });

        F.setSide('<div class="side-block"><div class="hd">盘点流程</div><div class="bd small" ' +
          'style="line-height:2">盘点中 → 待审核 → 已调整 → 已关闭' +
          '<div class="muted" style="margin-top:8px">· 差异率超过 0.5% 需二审<br>' +
          '· 审核放行后自动生成盘盈 / 盘亏流水并修正库存<br>· 调整同时修正货位体积占用</div></div></div>');
        F.setStatus("盘点作业 · " + d.total + " 张单据");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function openSt(no) {
      F.api("GET", "/api/stocktakes/" + no).then(function (v) {
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">盘点行数</div><div class="k-value">' + v.lineCount +
          '</div><div class="k-sub">' + F.esc(v.type) + " · " + F.esc(v.zone || "全仓") + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">差异行</div><div class="k-value">' + v.diffCount +
          '</div><div class="k-sub">差异率 ' + F.pct(v.lineCount ? v.diffCount / v.lineCount : 0, 2) +
          "</div></div>" +
          '<div class="kpi ' + (v.diffAmount < 0 ? "red" : "green") + '"><div class="k-label">损益金额</div>' +
          '<div class="k-value">' + F.num(v.diffAmount, 2) + '</div><div class="k-sub">按库存单价计</div></div>' +
          '<div class="kpi"><div class="k-label">状态</div><div class="k-value" style="font-size:16px">' +
          F.tag(v.status) + '</div><div class="k-sub">' + F.esc(v.operator) + " · " +
          F.esc(v.createdAt) + "</div></div></div>";

        html += F.table([
          { label: "货位", render: function (r) { return '<span class="mono">' + F.esc(r.location) + "</span>"; } },
          { label: "物料", render: function (r) { return '<b class="small">' + F.esc(r.item) + "</b>" +
            '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
          { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
          { label: "账面数", num: true, render: function (r) { return F.qty(r.bookQty); } },
          { label: "实盘数", render: function (r) {
            if (v.status !== "盘点中") return '<b>' + F.qty(r.actualQty) + "</b>";
            return '<input class="inp sm" data-cnt="' + r.id + '" type="number" value="' +
              (r.actualQty || r.bookQty) + '" style="width:90px">';
          } },
          { label: "差异", num: true, render: function (r) {
            if (!r.diffQty) return '<span class="muted">—</span>';
            return '<b class="' + (r.diffQty < 0 ? "red" : "green") + '">' +
              (r.diffQty > 0 ? "+" : "") + F.qty(r.diffQty) + "</b>";
          } },
          { label: "结果", render: function (r) { return F.tag(r.result); } },
          { label: "金额", num: true, render: function (r) { return r.amount ?
            F.num(r.amount, 2) : "—"; } }
        ], v.items, { empty: "无盘点明细" });

        var btns = [];
        if (v.status === "盘点中") btns.push(["save", "保存实盘数", "primary"]);
        if (v.status === "盘点中") btns.push(["stage:待审核", "提交审核", ""]);
        if (v.status === "待审核") btns.push(["stage:已调整", "审核并调整库存", "primary"]);
        if (v.status === "已调整") btns.push(["stage:已关闭", "关闭盘点", ""]);
        var foot = btns.map(function (b) {
          return '<button class="btn ' + b[2] + '" data-act="' + b[0] + '">' + b[1] + "</button>";
        }).join("") + '<button class="btn" data-close-foot="1">关闭</button>';

        var dlg = F.dialogWide("盘点单 " + v.no + " · " + v.status, html, foot);
        dlg.querySelector("[data-close-foot]").addEventListener("click", F.closeDialog);
        dlg.querySelectorAll("[data-act]").forEach(function (b) {
          b.addEventListener("click", function () {
            var act = b.getAttribute("data-act");
            if (act === "save") {
              var items = [];
              dlg.querySelectorAll("[data-cnt]").forEach(function (i) {
                items.push({ id: Number(i.getAttribute("data-cnt")), actualQty: Number(i.value || 0) });
              });
              F.api("POST", "/api/stocktakes/" + v.no + "/count", { items: items })
                .then(function (x) {
                  F.toast("已保存 " + x.counted + " 行，差异 " + x.diffLines + " 行", "ok");
                  F.closeDialog(); load(); F.boot();
                }).catch(function (e) { F.toast(e.message, "err"); });
              return;
            }
            if (act.indexOf("stage:") === 0) {
              F.api("POST", "/api/stocktakes/" + v.no + "/stage", { target: act.slice(6) })
                .then(function () {
                  F.toast("已推进到「" + act.slice(6) + "」", "ok");
                  F.closeDialog(); load(); F.boot();
                }).catch(function (e) { F.toast(e.message, "err"); });
            }
          });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });
})(window, document);
