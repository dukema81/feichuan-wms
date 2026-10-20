/* 飞传 WMS · 入库作业：到货通知（ASN）→ 收货 → 质检 → 上架 */
(function (window, document) {
  "use strict";
  var F = window.F;

  var ST = ["全部", "已预约", "已到货", "收货中", "已收货", "已上架", "已关闭"];

  F.register("inbound", function (params) {
    var st = params.st || "全部";
    var tab = params.tab || "asn";

    function load() {
      var q = st === "全部" ? "" : "&status=" + encodeURIComponent(st);
      Promise.all([
        F.api("GET", "/api/asns?limit=80" + q),
        F.api("GET", "/api/putaway?limit=60")
      ]).then(function (res) {
        var d = res[0], p = res[1];
        var c = d.counts || {};
        var pendingTask = (p.list || []).filter(function (x) { return x.status === "待执行"; });
        var html = '<div class="panel"><div class="panel-title">入库作业' +
          '<span class="panel-actions">' +
          '<button class="btn sm" id="asnNew">新建到货通知</button>' +
          '<button class="btn sm" id="asnRefresh">刷新</button></span></div>' +
          '<div class="panel-body">' +
          '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">待收货</div><div class="k-value">' +
          ((c["已到货"] || 0) + (c["收货中"] || 0)) +
          '</div><div class="k-sub">已到货 ' + (c["已到货"] || 0) + " · 收货中 " +
          (c["收货中"] || 0) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">在途预约</div><div class="k-value">' +
          (c["已预约"] || 0) + '</div><div class="k-sub">草稿 ' + (c["草稿"] || 0) + " 单</div></div>" +
          '<div class="kpi green"><div class="k-label">待上架任务</div><div class="k-value">' +
          pendingTask.length + '</div><div class="k-sub">已完成 ' +
          (p.list || []).filter(function (x) { return x.status === "已完成"; }).length +
          " 条</div></div>" +
          '<div class="kpi"><div class="k-label">已上架 / 已关闭</div><div class="k-value">' +
          ((c["已上架"] || 0) + (c["已关闭"] || 0)) +
          '</div><div class="k-sub">单据合计 ' + d.total + " 单</div></div></div>" +
          F.chips([["asn", "到货通知 (" + d.total + ")"], ["putaway", "上架任务 (" +
            pendingTask.length + ")"]], tab, "data-tab") +
          "</div></div>";

        html += '<div class="panel"><div class="panel-title">' +
          (tab === "asn" ? "到货通知" : "上架任务") +
          (tab === "asn" ? F.chips(ST.map(function (x) {
            return [x, x, x === "全部" ? d.total : (c[x] || 0)];
          }), st, "data-st") : "") +
          "</div><div class='panel-body flush' id='inBody'></div></div>";

        document.getElementById("view").innerHTML = html;

        var body = document.getElementById("inBody");
        if (tab === "asn") {
          body.innerHTML = F.table([
            { label: "单号", render: function (r) { return '<span class="mono">' + F.esc(r.no) + "</span>" +
              (r.priority === "加急" ? ' <span class="tag red">加急</span>' : ""); } },
            { label: "供应商", render: function (r) { return F.esc(r.supplierName) +
              '<div class="muted small mono">' + F.esc(r.poNo || "") + "</div>"; } },
            { label: "预约到货", render: function (r) { return '<span class="mono small">' +
              F.esc(r.expectDate) + "</span>"; } },
            { label: "行 / 量", num: true, render: function (r) {
              return r.lineCount + " 行 · " + F.qty(r.qty);
            } },
            { label: "收货进度", render: function (r) {
              return '<div class="util-cell">' + F.progress(r.receivedRate) +
                '<span class="small">' + F.pct(r.receivedRate, 0) + "</span></div>";
            } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "到货时间", render: function (r) { return '<span class="small muted">' +
              F.esc(r.arriveAt || "—") + "</span>"; } }
          ], d.list, { click: function (r) { return r.no; }, empty: "该状态下没有单据" });
          F.bindRows(document, openAsn);
        } else {
          body.innerHTML = F.table([
            { label: "任务号", render: function (r) { return '<span class="mono">' + F.esc(r.no) + "</span>"; } },
            { label: "ASN", render: function (r) { return '<span class="mono small">' + F.esc(r.asn_no) + "</span>"; } },
            { label: "物料", render: function (r) { return F.esc(r.item) +
              '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "建议货位", render: function (r) { return '<span class="mono small">' + F.esc(r.to_loc) + "</span>"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "", render: function (r) {
              return r.status === "待执行" ? '<button class="btn sm primary" data-put="' + F.esc(r.no) +
                '">执行上架</button>' : '<span class="small muted">' + F.esc(r.done_at || "") + "</span>";
            } }
          ], p.list, { empty: "暂无上架任务" });
          body.querySelectorAll("[data-put]").forEach(function (b) {
            b.addEventListener("click", function () { doPutaway(b.getAttribute("data-put")); });
          });
        }

        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("inbound", { st: b.getAttribute("data-st"), tab: tab });
          });
        });
        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("inbound", { st: st, tab: b.getAttribute("data-tab") });
          });
        });
        var nb = document.getElementById("asnNew");
        if (nb) nb.addEventListener("click", newAsn);
        var rf = document.getElementById("asnRefresh");
        if (rf) rf.addEventListener("click", function () { F.go("inbound", { st: st, tab: tab }); });

        F.setSide('<div class="side-block"><div class="hd">入库流程</div><div class="bd small" ' +
          'style="line-height:2">草稿 → 已预约 → 已到货 → 收货中 → 已收货 → 已上架 → 已关闭' +
          '<div class="muted" style="margin-top:8px">· 收货超收容差 5%、短少需填差异原因<br>' +
          '· 质检合格或让步接收才允许上架<br>· 上架完成即写库存与批次</div></div></div>');
        F.setStatus("入库作业 · " + d.total + " 张到货通知");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    /* ---------------- ASN 详情 ---------------- */
    function openAsn(no) {
      F.api("GET", "/api/asns/" + no).then(function (v) {
        var ctx = v.gate.ctx;
        var rows = (v.items || []).map(function (x) {
          return {
            line: x.line, item: x.item, name: x.name, qty: x.qty, receivedQty: x.receivedQty,
            lot: x.lot, expiry: x.expiry, qcStatus: x.qcStatus, diffReason: x.diffReason
          };
        });
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">计划数量</div><div class="k-value">' +
          F.qty(v.qty) + '</div><div class="k-sub">' + v.lineCount + " 行明细</div></div>" +
          '<div class="kpi green"><div class="k-label">已收数量</div><div class="k-value">' +
          F.qty(v.receivedQty) + '</div><div class="k-sub">完成度 ' + F.pct(v.receivedRate, 0) +
          "</div></div>" +
          '<div class="kpi"><div class="k-label">质检</div><div class="k-value">' +
          (ctx.qcDone ? (ctx.qcOk ? "合格" : "不合格") : "待检") +
          '</div><div class="k-sub">' + (ctx.qcDone ? "已完成判定" : "需抽检") + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">上架任务</div><div class="k-value">' +
          ctx.taskCount + '</div><div class="k-sub">' + (ctx.putawayDone ? "已全部完成" : "待执行") +
          "</div></div></div>";

        html += '<div class="kv-grid">' +
          F.kv("供应商", F.esc(v.supplierName) + ' <span class="muted small mono">' +
            F.esc(v.supplier) + "</span>") +
          F.kv("采购单号", F.esc(v.poNo || "—")) +
          F.kv("预约到货", F.esc(v.expectDate)) +
          F.kv("实际到货", F.esc(v.arriveAt || "—")) +
          F.kv("月台", F.esc(v.dock || "—")) +
          F.kv("当前状态", F.tag(v.status)) +
          F.kv("创建", F.esc(v.createdAt)) +
          F.kv("优先级", F.prio(v.priority)) + "</div>";

        html += '<div class="gate-box"><div class="gate-hd">状态闸口</div>' +
          (v.gate.gates || []).map(function (g) {
            return '<div class="gate ' + (g.ok ? "ok" : "bad") + '"><b>' +
              (g.ok ? "✓" : "✕") + " " + F.esc(g.target) + "</b>" +
              (g.ok ? '<span class="muted small">可以推进</span>' :
                "<span>" + g.missing.map(F.esc).join("；") + "</span>") + "</div>";
          }).join("") + "</div>";

        html += '<div class="sub-title">收货明细</div>' + F.table([
          { label: "#", render: function (r) { return r.line; } },
          { label: "物料", render: function (r) { return F.esc(r.item) +
            '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
          { label: "计划", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "已收", num: true, render: function (r) { return F.qty(r.receivedQty); } },
          { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
          { label: "有效期", render: function (r) { return '<span class="small">' + F.esc(r.expiry || "—") + "</span>"; } },
          { label: "质检", render: function (r) { return F.tag(r.qcStatus); } }
        ], rows);

        if ((v.tasks || []).length) {
          html += '<div class="sub-title">上架任务</div>' + F.table([
            { label: "任务号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "物料", render: function (r) { return F.esc(r.item); } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "目标货位", render: function (r) { return '<span class="mono small">' + F.esc(r.to_loc) + "</span>"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "", render: function (r) {
              return r.status === "待执行" ? '<button class="btn sm primary" data-put="' + F.esc(r.no) +
                '">执行上架</button>' : "";
            } }
          ], v.tasks);
        }

        var btns = [];
        if (v.status === "草稿") btns.push(["stage:已预约", "预约到货", "primary"]);
        if (v.status === "已预约") btns.push(["stage:已到货", "登记到货", "primary"]);
        if (v.status === "已到货" || v.status === "收货中") btns.push(["receive", "登记收货", "primary"]);
        if (v.status === "收货中") btns.push(["stage:已收货", "收货完成", ""]);
        if (v.status === "已收货") {
          btns.push(["qc", "质检判定", ""]);
          btns.push(["putaway", "生成上架任务", "primary"]);
        }
        if (v.status === "已上架") btns.push(["stage:已关闭", "关闭单据", "primary"]);
        if (v.gate.cancelable) btns.push(["cancel", "取消单据", "danger"]);
        var foot = btns.map(function (b) {
          return '<button class="btn ' + b[2] + '" data-act="' + b[0] + '">' + b[1] + "</button>";
        }).join("") + '<button class="btn" data-close-foot="1">关闭</button>';

        var dlg = F.dialogWide("到货通知 " + v.no + " · " + v.status, html, foot);
        dlg.querySelector("[data-close-foot]").addEventListener("click", F.closeDialog);
        dlg.querySelectorAll("[data-act]").forEach(function (b) {
          b.addEventListener("click", function () {
            var act = b.getAttribute("data-act");
            if (act.indexOf("stage:") === 0) return doStage(v.no, act.slice(6));
            if (act === "receive") return doReceive(v);
            if (act === "qc") return doQc(v);
            if (act === "putaway") return doPutawayGen(v.no);
            if (act === "cancel") return doCancel(v.no);
          });
        });
        dlg.querySelectorAll("[data-put]").forEach(function (b) {
          b.addEventListener("click", function () { doPutaway(b.getAttribute("data-put")); });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doStage(no, target) {
      F.api("POST", "/api/asns/" + no + "/stage", { target: target, arriveAt: null })
        .then(function () {
          F.toast("已推进到「" + target + "」", "ok");
          F.closeDialog(); load(); F.boot();
        }).catch(function (e) {
          F.toast(e.message, "err");
        });
    }

    function doReceive(v) {
      var pending = (v.items || []).filter(function (x) { return x.receivedQty < x.qty; });
      if (!pending.length) { F.toast("所有明细已收齐，可直接点「收货完成」", "err"); return; }
      var body = '<div class="form-grid">' + pending.map(function (x) {
        var left = x.qty - x.receivedQty;
        return '<label class="full">' + F.esc(x.item) + " " + F.esc(x.name) +
          ' <span class="muted small">待收 ' + F.qty(left) + "</span>" +
          '<div class="row-flex"><input class="inp" data-recv="' + x.line + '" type="number" value="' +
          left + '" min="0" max="' + left + '" step="1">' +
          '<input class="inp" data-lot="' + x.line + '" value="' + F.esc(x.lot) + '" placeholder="批次">' +
          '<input class="inp" data-exp="' + x.line + '" value="' + F.esc(x.expiry || "") +
          '" placeholder="有效期 YYYY-MM-DD"></div></label>';
      }).join("") + "</div>";
      F.dialog("登记收货 · " + v.no, body, '<button class="btn primary" id="rvOk">确认收货</button>');
      document.getElementById("rvOk").addEventListener("click", function () {
        var items = [];
        pending.forEach(function (x) {
          var q = Number(document.querySelector('[data-recv="' + x.line + '"]').value || 0);
          if (q > 0) {
            items.push({ line: x.line, qty: q,
              lot: document.querySelector('[data-lot="' + x.line + '"]').value.trim(),
              expiry: document.querySelector('[data-exp="' + x.line + '"]').value.trim() });
          }
        });
        if (!items.length) { F.toast("请输入收货数量", "err"); return; }
        F.api("POST", "/api/asns/" + v.no + "/receive", { items: items }).then(function () {
          F.toast("收货成功", "ok");
          F.closeDialog(); load(); F.boot();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function doQc(v) {
      var got = (v.items || []).filter(function (x) { return x.receivedQty > 0; });
      var body = '<div class="form-grid">' +
        '<label>质检结论<select id="qcRes"><option>合格</option><option>让步接收</option>' +
        "<option>不合格</option></select></label>" +
        '<label>抽检数量<input id="qcQty" type="number" placeholder="留空按规则 10%"></label>' +
        '<label class="full">说明<input id="qcNote" placeholder="如 外箱轻微破损，让步接收"></label>' +
        "</div><div class='muted small'>将对 " + got.length + " 行已收明细统一判定。</div>";
      F.dialog("来料质检 · " + v.no, body, '<button class="btn primary" id="qcOk">提交判定</button>');
      document.getElementById("qcOk").addEventListener("click", function () {
        var q = Number(document.getElementById("qcQty").value || 0);
        F.api("POST", "/api/asns/" + v.no + "/qc", {
          result: document.getElementById("qcRes").value, qcQty: q || undefined
        }).then(function () {
          F.toast("质检已判定", "ok");
          F.closeDialog(); load(); F.boot();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function doPutawayGen(no) {
      F.api("POST", "/api/asns/" + no + "/putaway", {}).then(function (x) {
        F.toast("已生成 " + x.created + " 条上架任务", "ok");
        F.closeDialog(); load(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doPutaway(no) {
      F.api("GET", "/api/locations?limit=400").then(function (loc) {
        var body = '<div class="form-grid">' +
          '<label class="full">目标货位<select id="puLoc">' + (loc.list || []).map(function (l) {
            return '<option value="' + F.esc(l.code) + '">' + F.esc(l.code) + " · " +
              F.esc(l.kind) + " · 余 " + F.cube(l.capacity - l.used) + "</option>";
          }).join("") + "</select></label></div>";
        F.dialog("执行上架 " + no, body, '<button class="btn primary" id="puOk">确认上架</button>');
        document.getElementById("puOk").addEventListener("click", function () {
          F.api("POST", "/api/putaway/" + no + "/done",
            { to: document.getElementById("puLoc").value }).then(function (x) {
            F.toast("上架完成 → " + x.to, "ok");
            F.closeDialog(); load(); F.boot();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doCancel(no) {
      F.api("POST", "/api/asns/" + no + "/cancel", {}).then(function () {
        F.toast("单据已取消", "ok");
        F.closeDialog(); load(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    /* ---------------- 新建 ASN ---------------- */
    function newAsn() {
      Promise.all([F.api("GET", "/api/suppliers"), F.api("GET", "/api/items?limit=200")])
        .then(function (res) {
          var sup = res[0].list || [], items = res[1].list || [];
          var body = '<div class="form-grid">' +
            '<label>供应商<select id="asSup">' + sup.map(function (s) {
              return '<option value="' + F.esc(s.code) + '">' + F.esc(s.code) + " " +
                F.esc(s.name) + "</option>";
            }).join("") + "</select></label>" +
            '<label>采购单号<input id="asPo" placeholder="PO2026001"></label>' +
            '<label>预约到货<input id="asDate" type="date" value="' + F.today() + '"></label>' +
            '<label>优先级<select id="asPrio"><option>普通</option><option>加急</option></select></label>' +
            '<label>月台<input id="asDock" placeholder="DH-01"></label>' +
            '<label>备注<input id="asNote" placeholder="选填"></label>' +
            '<label class="full">明细</label></div>' +
            '<div id="asLines">' + lineRow(items) + "</div>" +
            '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn sm" id="asAdd">+ 增加一行</button></div>' +
            '<div class="muted small">批次与有效期留空则按物料保质期自动生成。</div>';
          F.dialogWide("新建到货通知", body, '<button class="btn primary" id="asOk">创建</button>');
          document.getElementById("asAdd").addEventListener("click", function () {
            var box = document.getElementById("asLines");
            box.insertAdjacentHTML("beforeend", lineRow(items));
          });
          document.getElementById("asOk").addEventListener("click", function () {
            var list = [];
            document.querySelectorAll("#asLines .line-row").forEach(function (r) {
              var code = r.querySelector("[data-item]").value;
              var qty = Number(r.querySelector("[data-qty]").value || 0);
              if (code && qty > 0) {
                list.push({ item: code, qty: qty,
                  lot: r.querySelector("[data-lot]").value.trim(),
                  expiry: r.querySelector("[data-exp]").value.trim() });
              }
            });
            if (!list.length) { F.toast("请至少填写一行明细", "err"); return; }
            F.api("POST", "/api/asns", {
              supplier: document.getElementById("asSup").value,
              poNo: document.getElementById("asPo").value.trim(),
              expectDate: document.getElementById("asDate").value,
              priority: document.getElementById("asPrio").value,
              dock: document.getElementById("asDock").value.trim(),
              note: document.getElementById("asNote").value.trim(),
              items: list
            }).then(function (x) {
              F.closeDialog();
              F.toast("已创建 " + x.no + "，共 " + x.lines + " 行", "ok");
              F.go("inbound", { st: "全部", tab: "asn" });
              F.boot();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function lineRow(items) {
      return '<div class="line-row row-flex">' +
        '<select class="inp" data-item>' + items.map(function (i) {
          return '<option value="' + F.esc(i.code) + '">' + F.esc(i.code) + " " +
            F.esc(i.name) + "</option>";
        }).join("") + "</select>" +
        '<input class="inp" data-qty type="number" placeholder="数量" style="max-width:100px">' +
        '<input class="inp" data-lot placeholder="批次（可空）">' +
        '<input class="inp" data-exp placeholder="有效期（可空）">' +
        "</div>";
    }

    load();
  });
})(window, document);
