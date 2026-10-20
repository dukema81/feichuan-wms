/* 飞传 WMS · 出库作业与波次拣货 */
(function (window, document) {
  "use strict";
  var F = window.F;

  var SO_ST = ["全部", "已提交", "已分配", "拣货中", "已拣货", "已复核", "已发运", "已签收"];

/* ---------------- 波次 ---------------- */
function loadWaves() {
  Promise.all([
    F.api("GET", "/api/waves?limit=40"),
    F.api("GET", "/api/waves/candidates")
  ]).then(function (res) {
    var d = res[0], cand = res[1];
    var c = d.counts || {};
    var groups = cand.groups || [];
    var html = '<div class="panel"><div class="panel-title">波次拣货' +
      '<span class="panel-actions">' +
      '<select class="inp sm" id="wvRule">' + (cand.rules || []).map(function (r) {
        return '<option value="' + F.esc(r) + '">按' + F.esc(r) + "组波</option>";
      }).join("") + "</select>" +
      '<button class="btn sm primary" id="wvNew">生成波次</button></span></div>' +
      '<div class="panel-body"><div class="kpi-grid four">' +
      '<div class="kpi"><div class="k-label">待拣波次</div><div class="k-value">' +
      ((c["待拣"] || 0) + (c["拣货中"] || 0)) + '</div><div class="k-sub">已完成 ' +
      (c["已完成"] || 0) + " 个</div></div>" +
      '<div class="kpi gold"><div class="k-label">可组波订单</div><div class="k-value">' +
      (cand.orders || []).length + '</div><div class="k-sub">已分配未进波次</div></div>' +
      '<div class="kpi green"><div class="k-label">建议波次数</div><div class="k-value">' +
      groups.length + '</div><div class="k-sub">均衡度 ' +
      F.num(cand.balance, 2) + "（越小越均衡）</div></div>" +
      '<div class="kpi"><div class="k-label">待拣任务</div><div class="k-value">' +
      (F.state.boot ? F.state.boot.kpi.pickPending : "—") +
      '</div><div class="k-sub">行数口径</div></div></div></div></div>';

    html += '<div class="panel"><div class="panel-title">待组波订单' +
      '<span class="panel-actions small muted">选中后生成波次，或直接点「生成波次」由系统按规则组波</span>' +
      "</div><div class='panel-body flush'>" +
      F.table([
        { label: "", render: function (r) {
          return '<input type="checkbox" data-pick="' + F.esc(r.no) + '">';
        } },
        { label: "单号", render: function (r) { return '<span class="mono">' + F.esc(r.no) + "</span>"; } },
        { label: "客户", render: function (r) { return F.esc(r.customerName); } },
        { label: "优先级", render: function (r) { return F.prio(r.priority); } },
        { label: "截单", render: function (r) { return F.esc(r.cutoff); } },
        { label: "承运商", render: function (r) { return F.esc(r.carrier); } },
        { label: "行数", num: true, render: function (r) { return r.lineCount; } },
        { label: "体积", num: true, render: function (r) { return F.cube(r.cube); } }
      ], cand.orders || [], { empty: "没有待组波订单（先做出库分配）" }) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">波次列表</div><div class="panel-body flush">' +
      F.table([
        { label: "波次号", render: function (r) { return '<span class="mono">' + F.esc(r.no) + "</span>"; } },
        { label: "规则 / 承运商", render: function (r) { return F.esc(r.rule) + " · " +
          F.esc(r.carrier); } },
        { label: "订单", num: true, render: function (r) { return r.orderCnt + " 单"; } },
        { label: "行数", num: true, render: function (r) { return r.lineCnt + " 行"; } },
        { label: "体积 / 重量", num: true, render: function (r) {
          return F.cube(r.cube) + " · " + F.num(r.weight, 1) + " kg";
        } },
        { label: "状态", render: function (r) { return F.tag(r.status); } },
        { label: "", render: function (r) {
          if (r.status === "已完成") return '<span class="small muted">' + F.esc(r.doneAt || "") + "</span>";
          if (r.status === "待拣") return '<button class="btn sm primary" data-rel="' + F.esc(r.no) +
            '">下发拣货</button>';
          return '<button class="btn sm primary" data-wpick="' + F.esc(r.no) + '">整波拣货</button>' +
            ' <button class="btn sm" data-wdone="' + F.esc(r.no) + '">完成</button>';
        } }
      ], d.list, { empty: "暂无波次" }) + "</div></div>";

    document.getElementById("view").innerHTML = html;

    document.getElementById("wvNew").addEventListener("click", function () {
      var picked = [];
      document.querySelectorAll("[data-pick]:checked").forEach(function (c) {
        picked.push(c.getAttribute("data-pick"));
      });
      F.api("POST", "/api/waves", { rule: document.getElementById("wvRule").value,
        orders: picked }).then(function (x) {
        F.toast("已生成 " + x.created + " 个波次", "ok");
        loadWaves(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    });
    document.querySelectorAll("[data-rel]").forEach(function (b) {
      b.addEventListener("click", function () {
        F.api("POST", "/api/waves/" + b.getAttribute("data-rel") + "/release", {})
          .then(function () { F.toast("波次已下发，开始拣货", "ok"); loadWaves(); })
          .catch(function (e) { F.toast(e.message, "err"); });
      });
    });
    document.querySelectorAll("[data-wpick]").forEach(function (b) {
      b.addEventListener("click", function () {
        F.api("POST", "/api/waves/" + b.getAttribute("data-wpick") + "/pick", {})
          .then(function (x) {
            F.toast("整波拣货完成 " + x.lines + " 行" + (x.short.length ?
              "，短拣 " + x.short.length + " 行" : ""), x.short.length ? "err" : "ok");
            loadWaves(); F.boot();
          }).catch(function (e) { F.toast(e.message, "err"); });
      });
    });
    document.querySelectorAll("[data-wdone]").forEach(function (b) {
      b.addEventListener("click", function () {
        F.api("POST", "/api/waves/" + b.getAttribute("data-wdone") + "/done", {})
          .then(function () { F.toast("波次已完成", "ok"); loadWaves(); F.boot(); })
          .catch(function (e) { F.toast(e.message, "err"); });
      });
    });

    F.setSide('<div class="side-block"><div class="hd">组波说明</div><div class="bd small muted" ' +
      'style="line-height:1.9">波次把多张已分配订单合并成一次拣货任务，按承运商 / 截单时段 / ' +
      '客户 / 库区聚类，单波上限 12 单、120 行；拣货任务按货位蛇形排序，减少回头路。</div></div>');
    F.setStatus("波次拣货 · " + (d.total || 0) + " 个波次");
  }).catch(function (e) { F.toast(e.message, "err"); });
}



  F.register("outbound", function (params) {
    var st = params.st || "全部";
    var tab = params.tab || "orders";

    function load() {
      if (tab === "waves") return loadWaves();
      var q = st === "全部" ? "" : "&status=" + encodeURIComponent(st);
      Promise.all([
        F.api("GET", "/api/orders?limit=80" + q),
        F.api("GET", "/api/waves?limit=40")
      ]).then(function (res) {
        var d = res[0], w = res[1];
        var c = d.counts || {};
        var pendingShip = (w.list || []).filter(function (x) { return x.status !== "已完成"; }).length;
        var html = '<div class="panel"><div class="panel-title">出库作业' +
          '<span class="panel-actions">' +
          '<button class="btn sm" id="soNew">新建出库单</button>' +
          '<button class="btn sm" id="soRefresh">刷新</button></span></div>' +
          '<div class="panel-body"><div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">待分配</div><div class="k-value">' +
          ((c["已提交"] || 0) + (c["草稿"] || 0)) +
          '</div><div class="k-sub">已提交 ' + (c["已提交"] || 0) + " · 草稿 " +
          (c["草稿"] || 0) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">拣货在途</div><div class="k-value">' +
          ((c["已分配"] || 0) + (c["拣货中"] || 0)) +
          '</div><div class="k-sub">已拣货 ' + (c["已拣货"] || 0) + " 单</div></div>" +
          '<div class="kpi green"><div class="k-label">待发运</div><div class="k-value">' +
          (c["已复核"] || 0) + '</div><div class="k-sub">在途波次 ' + pendingShip + " 个</div></div>" +
          '<div class="kpi"><div class="k-label">已发运 / 签收</div><div class="k-value">' +
          ((c["已发运"] || 0) + (c["已签收"] || 0)) +
          '</div><div class="k-sub">单据合计 ' + d.total + " 单</div></div></div>" +
          F.chips([["orders", "出库单 (" + d.total + ")"], ["waves", "波次 (" +
            (w.total || 0) + ")"]], tab, "data-tab") + "</div></div>";

        html += '<div class="panel"><div class="panel-title">出库单' +
          F.chips(SO_ST.map(function (x) {
            return [x, x, x === "全部" ? d.total : (c[x] || 0)];
          }), st, "data-st") + "</div><div class='panel-body flush' id='soBody'></div></div>";
        document.getElementById("view").innerHTML = html;

        document.getElementById("soBody").innerHTML = F.table([
          { label: "单号", render: function (r) { return '<span class="mono">' + F.esc(r.no) + "</span>"; } },
          { label: "客户", render: function (r) { return F.esc(r.customerName) +
            '<div class="muted small">' + F.esc(r.dest || "") + "</div>"; } },
          { label: "优先级", render: function (r) { return F.prio(r.priority) +
            ' <span class="muted small">' + F.esc(r.cutoff) + " 截单</span>"; } },
          { label: "行 / 量", num: true, render: function (r) {
            return r.lineCount + " 行 · " + F.qty(r.qty);
          } },
          { label: "满足率", render: function (r) {
            return '<div class="util-cell">' + F.progress(r.fillRate || r.progress) +
              '<span class="small">' + F.pct(r.fillRate || 0, 0) + "</span></div>";
          } },
          { label: "承运", render: function (r) { return '<span class="small">' +
            F.esc(r.carrier) + "</span>"; } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "波次", render: function (r) { return r.waveNo ?
            '<span class="mono small">' + F.esc(r.waveNo.slice(-4)) + "</span>" : "—"; } }
        ], d.list, { click: function (r) { return r.no; }, empty: "该状态下没有单据" });
        F.bindRows(document, openOrder);

        document.querySelectorAll("[data-st]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("outbound", { st: b.getAttribute("data-st"), tab: "orders" });
          });
        });
        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () {
            if (b.getAttribute("data-tab") === "waves") return F.go("wave");
            F.go("outbound", { st: st, tab: "orders" });
          });
        });
        document.getElementById("soNew").addEventListener("click", newOrder);
        document.getElementById("soRefresh").addEventListener("click", function () {
          F.go("outbound", { st: st, tab: "orders" });
        });

        F.setSide('<div class="side-block"><div class="hd">出库流程</div><div class="bd small" ' +
          'style="line-height:2">已提交 → 已分配 → 拣货中 → 已拣货 → 已复核 → 已发运 → 已签收' +
          '<div class="muted" style="margin-top:8px">· 分配按 FEFO（先到期先出）锁定库存<br>' +
          '· 拣货确认即扣减库存并写流水<br>· 复核打包生成包裹与运单号</div></div></div>');
        F.setStatus("出库作业 · " + d.total + " 张出库单");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    /* ---------------- 订单详情 ---------------- */
    function openOrder(no) {
      F.api("GET", "/api/orders/" + no).then(function (v) {
        var ctx = v.gate.ctx;
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">订单数量</div><div class="k-value">' +
          F.qty(v.qty) + '</div><div class="k-sub">' + v.lineCount + " 行 · " +
          F.wan(v.amount) + " 元</div></div>" +
          '<div class="kpi green"><div class="k-label">已分配</div><div class="k-value">' +
          F.qty(v.allocatedQty) + '</div><div class="k-sub">满足率 ' + F.pct(v.fillRate, 1) +
          "</div></div>" +
          '<div class="kpi gold"><div class="k-label">已拣货</div><div class="k-value">' +
          F.qty(v.pickedQty) + '</div><div class="k-sub">进度 ' + F.pct(v.progress, 0) + "</div></div>" +
          '<div class="kpi"><div class="k-label">重量 / 体积</div><div class="k-value">' +
          F.num(v.weight, 1) + " kg</div><div class=\"k-sub\">" + F.cube(v.cube) + "</div></div></div>";

        html += '<div class="kv-grid">' +
          F.kv("客户", F.esc(v.customerName) + ' <span class="muted small">' +
            F.esc(v.customerLevel) + "</span>") +
          F.kv("承运商", F.esc(v.carrier) + " · " + F.esc(v.cutoff) + " 截单") +
          F.kv("优先级", F.prio(v.priority)) +
          F.kv("状态", F.tag(v.status)) +
          F.kv("波次", F.esc(v.waveNo || "—")) +
          F.kv("运单号", F.esc(v.trackingNo || "—")) +
          F.kv("创建", F.esc(v.createdAt)) +
          F.kv("发运", F.esc(v.shippedAt || "—")) + "</div>";

        html += '<div class="gate-box"><div class="gate-hd">状态闸口</div>' +
          (v.gate.gates || []).map(function (g) {
            return '<div class="gate ' + (g.ok ? "ok" : "bad") + '"><b>' +
              (g.ok ? "✓" : "✕") + " " + F.esc(g.target) + "</b>" +
              (g.ok ? '<span class="muted small">可以推进</span>' :
                "<span>" + g.missing.map(F.esc).join("；") + "</span>") + "</div>";
          }).join("") + "</div>";

        html += '<div class="sub-title">出库明细</div>' + F.table([
          { label: "#", render: function (r) { return r.line; } },
          { label: "物料", render: function (r) { return F.esc(r.item) +
            '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "已分配", num: true, render: function (r) { return F.qty(r.allocatedQty); } },
          { label: "已拣", num: true, render: function (r) { return F.qty(r.pickedQty); } },
          { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot || "—") + "</span>"; } },
          { label: "货位", render: function (r) { return '<span class="mono small">' + F.esc(r.location || "—") + "</span>"; } },
          { label: "金额", num: true, render: function (r) { return F.num(r.qty * r.price, 0); } }
        ], v.items);

        if ((v.allocations || []).length) {
          html += '<div class="sub-title">分配明细（' + v.allocations.length + ' 条）</div>' + F.table([
            { label: "物料", render: function (r) { return F.esc(r.item); } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "货位", render: function (r) { return '<span class="mono small">' + F.esc(r.location) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], v.allocations.slice(0, 12));
        }

        if ((v.picks || []).length) {
          html += '<div class="sub-title">拣货任务（按货位蛇形排序 · 行走 ' +
            F.num(v.pathDistance, 0) + " 米 · 预计 " + F.num(v.pickMinutes, 1) + " 分钟）</div>" +
            F.table([
              { label: "序", render: function (r) { return "P" + (r.seq < 10 ? "0" : "") + r.seq; } },
              { label: "任务号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "货位", render: function (r) { return '<span class="mono">' + F.esc(r.from_loc) + "</span>"; } },
              { label: "物料", render: function (r) { return F.esc(r.item) +
                '<div class="muted small">' + F.esc(r.name) + "</div>"; } },
              { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
              { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } }
            ], v.picks);
        }

        if ((v.packages || []).length) {
          html += '<div class="sub-title">包裹与运单</div>' + F.table([
            { label: "包裹号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "箱数", num: true, render: function (r) { return r.boxes; } },
            { label: "重量", num: true, render: function (r) { return F.num(r.weight, 1) + " kg"; } },
            { label: "体积", num: true, render: function (r) { return F.cube(r.cube); } },
            { label: "运单号", render: function (r) { return F.esc(r.tracking_no || "—"); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], v.packages);
        }

        var btns = [];
        if (v.status === "草稿") btns.push(["stage:已提交", "提交订单", "primary"]);
        if (v.status === "已提交" || v.status === "已分配") btns.push(["alloc", "库存分配", "primary"]);
        if (v.status === "已分配" || v.status === "拣货中") btns.push(["pick", "拣货确认", "primary"]);
        if (v.status === "已拣货") btns.push(["pack", "复核打包", "primary"]);
        if (v.status === "已复核") btns.push(["ship", "发运出库", "primary"]);
        if (v.status === "已发运") btns.push(["stage:已签收", "登记签收", "primary"]);
        btns.push(["picklist", "拣货单", ""]);
        if (v.gate.cancelable) btns.push(["cancel", "取消订单", "danger"]);
        var foot = btns.map(function (b) {
          return '<button class="btn ' + b[2] + '" data-act="' + b[0] + '">' + b[1] + "</button>";
        }).join("") + '<button class="btn" data-close-foot="1">关闭</button>';

        var dlg = F.dialogWide("出库单 " + v.no + " · " + v.status, html, foot);
        dlg.querySelector("[data-close-foot]").addEventListener("click", F.closeDialog);
        dlg.querySelectorAll("[data-act]").forEach(function (b) {
          b.addEventListener("click", function () {
            var act = b.getAttribute("data-act");
            if (act.indexOf("stage:") === 0) return doStage(v.no, act.slice(6));
            if (act === "alloc") return doAlloc(v.no);
            if (act === "pick") return doPick(v.no);
            if (act === "pack") return doPack(v);
            if (act === "ship") return doShip(v);
            if (act === "picklist") return showPicklist(v.no);
            if (act === "cancel") return doCancel(v.no);
          });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doStage(no, target) {
      F.api("POST", "/api/orders/" + no + "/stage", { target: target }).then(function () {
        F.toast("已推进到「" + target + "」", "ok");
        F.closeDialog(); load(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doAlloc(no) {
      F.api("POST", "/api/orders/" + no + "/alloc", {}).then(function (x) {
        if (x.short && x.short.length) {
          F.toast("分配完成，满足率 " + F.pct(x.fillRate, 0) + "，缺量 " + x.short.length + " 行", "err");
        } else {
          F.toast("分配完成，满足率 " + F.pct(x.fillRate, 0) + "（" + x.strategy + "）", "ok");
        }
        F.closeDialog(); load(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doPick(no) {
      F.api("POST", "/api/orders/" + no + "/pick", {}).then(function (x) {
        F.toast("拣货完成 " + x.lines + " 行，共 " + F.qty(x.qty) + " 件", "ok");
        F.closeDialog(); load(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doPack(v) {
      var body = '<div class="form-grid">' +
        '<label>箱数<input id="pkBoxes" type="number" placeholder="留空自动估算"></label>' +
        "</div><div class='muted small'>重量 " + F.num(v.weight, 1) + " kg · 体积 " +
        F.cube(v.cube) + "，系统按 18kg/箱与体积双约束估算箱数。</div>";
      F.dialog("复核打包 · " + v.no, body, '<button class="btn primary" id="pkOk">确认打包</button>');
      document.getElementById("pkOk").addEventListener("click", function () {
        var n = Number(document.getElementById("pkBoxes").value || 0);
        F.api("POST", "/api/orders/" + v.no + "/pack", { boxes: n || undefined }).then(function (x) {
          F.toast("打包完成：" + x.boxes + " 箱 / " + F.num(x.weight, 1) + " kg", "ok");
          F.closeDialog(); load(); F.boot();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    function doShip(v) {
      F.api("GET", "/api/carriers").then(function (c) {
        var body = '<div class="form-grid">' +
          '<label>承运商<select id="shCar">' + (c.list || []).map(function (x) {
            return '<option value="' + F.esc(x.code) + '"' + (x.code === v.carrier ? " selected" : "") +
              ">" + F.esc(x.name) + "（" + F.esc(x.cutoff) + " 截单）</option>";
          }).join("") + "</select></label>" +
          '<label>运单号<input id="shTrack" placeholder="留空自动生成"></label></div>';
        F.dialog("发运出库 · " + v.no, body, '<button class="btn primary" id="shOk">确认发运</button>');
        document.getElementById("shOk").addEventListener("click", function () {
          F.api("POST", "/api/orders/" + v.no + "/ship", {
            carrier: document.getElementById("shCar").value,
            trackingNo: document.getElementById("shTrack").value.trim()
          }).then(function (x) {
            F.toast("已发运，运单号 " + x.trackingNo, "ok");
            F.closeDialog(); load(); F.boot();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function showPicklist(no) {
      F.api("GET", "/api/orders/" + no + "/picklist").then(function (v) {
        var html = '<div class="kv-grid">' +
          F.kv("出库单", F.esc(v.no)) + F.kv("客户", F.esc(v.customer)) +
          F.kv("承运商", F.esc(v.carrier)) + F.kv("优先级", F.prio(v.priority)) +
          F.kv("行走距离", F.num(v.distance, 0) + " 米") +
          F.kv("预计工时", F.num(v.minutes, 1) + " 分钟") + "</div>" +
          '<div class="sub-title">拣货路径（蛇形排序）</div>' +
          F.table([
            { label: "序", render: function (r, i) { return "P" + ((i + 1) < 10 ? "0" : "") + (i + 1); } },
            { label: "货位", render: function (r) { return '<span class="mono">' + F.esc(r.from_loc) + "</span>"; } },
            { label: "物料", render: function (r) { return F.esc(r.item) + " " +
              '<span class="muted small">' + F.esc(r.name || "") + "</span>"; } },
            { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } }
          ], v.lines) +
          '<div class="muted small" style="margin-top:8px">路径：' + (v.path || []).join(" → ") + "</div>";
        F.dialogWide("拣货单 " + v.no, html, '<button class="btn" onclick="window.print()">打印</button>');
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function doCancel(no) {
      F.api("POST", "/api/orders/" + no + "/cancel", {}).then(function () {
        F.toast("订单已取消，锁定库存已释放", "ok");
        F.closeDialog(); load(); F.boot();
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    /* ---------------- 新建出库单 ---------------- */
    function newOrder() {
      Promise.all([F.api("GET", "/api/customers"), F.api("GET", "/api/items?limit=200")])
        .then(function (res) {
          var cust = res[0].list || [], items = res[1].list || [];
          var body = '<div class="form-grid">' +
            '<label>客户<select id="soCust">' + cust.map(function (c) {
              return '<option value="' + F.esc(c.code) + '">' + F.esc(c.code) + " " +
                F.esc(c.name) + "（" + F.esc(c.level) + "）</option>";
            }).join("") + "</select></label>" +
            '<label>优先级<select id="soPrio"><option>普通</option><option>加急</option>' +
            "<option>特急</option></select></label>" +
            '<label>截单时间<input id="soCut" type="time" value="18:00"></label>' +
            '<label>收货地址<input id="soDest" placeholder="选填"></label>' +
            '<label class="full">明细</label></div>' +
            '<div id="soLines">' + soLine(items) + "</div>" +
            '<div class="form-foot" style="justify-content:flex-start">' +
            '<button class="btn sm" id="soAdd">+ 增加一行</button></div>' +
            '<div class="muted small">提交后可在详情里做库存分配（FEFO）。</div>';
          F.dialogWide("新建出库单", body, '<button class="btn primary" id="soOk">创建</button>');
          document.getElementById("soAdd").addEventListener("click", function () {
            document.getElementById("soLines").insertAdjacentHTML("beforeend", soLine(items));
          });
          document.getElementById("soOk").addEventListener("click", function () {
            var list = [];
            document.querySelectorAll("#soLines .line-row").forEach(function (r) {
              var code = r.querySelector("[data-item]").value;
              var q = Number(r.querySelector("[data-qty]").value || 0);
              if (code && q > 0) list.push({ item: code, qty: q });
            });
            if (!list.length) { F.toast("请至少填写一行明细", "err"); return; }
            F.api("POST", "/api/orders", {
              customer: document.getElementById("soCust").value,
              priority: document.getElementById("soPrio").value,
              cutoff: document.getElementById("soCut").value,
              dest: document.getElementById("soDest").value.trim(),
              items: list
            }).then(function (x) {
              F.closeDialog();
              F.toast("已创建 " + x.no + "，共 " + x.lines + " 行", "ok");
              F.go("outbound", { st: "全部", tab: "orders" });
              F.boot();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function soLine(items) {
      return '<div class="line-row row-flex">' +
        '<select class="inp" data-item>' + items.map(function (i) {
          return '<option value="' + F.esc(i.code) + '">' + F.esc(i.code) + " " + F.esc(i.name) +
            "（库存 " + F.qty(i.stockQty) + "）</option>";
        }).join("") + "</select>" +
        '<input class="inp" data-qty type="number" placeholder="数量" style="max-width:110px">' +
        "</div>";
    }

    load();
  });

  /* 波次拣货独立页面 */
  F.register("wave", function () { loadWaves(); });
})(window, document);
