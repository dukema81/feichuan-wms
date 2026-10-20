/* 飞传 WMS · 物料主数据与往来单位 */
(function (window, document) {
  "use strict";
  var F = window.F;

  /* ============================================================ 物料主数据 */
  F.register("items", function (params) {
    var cat = params.cat || "";
    var abc = params.abc || "";
    var q = params.q || "";

    function load() {
      var qs = "?limit=200" + (cat ? "&category=" + encodeURIComponent(cat) : "") +
        (abc ? "&abc=" + encodeURIComponent(abc) : "") + (q ? "&q=" + encodeURIComponent(q) : "");
      F.api("GET", "/api/items" + qs).then(function (d) {
        var list = d.list || [];
        var cats = d.categories || [];
        var totalQty = list.reduce(function (a, x) { return a + x.stockQty; }, 0);
        var totalVal = list.reduce(function (a, x) { return a + x.stockQty * x.price; }, 0);
        var low = list.filter(function (x) { return x.level === "不足" || x.level === "断货"; }).length;
        var aCount = list.filter(function (x) { return x.abc === "A"; }).length;

        var html = '<div class="panel"><div class="panel-title">物料主数据' +
          '<span class="panel-actions">' +
          '<input class="inp sm" id="itQ" placeholder="编码/名称/条码" value="' + F.esc(q) + '">' +
          '<button class="btn sm" id="itGo">查询</button>' +
          '<button class="btn sm primary" id="itNew">新建物料</button></span></div>' +
          '<div class="panel-body"><div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">物料数</div><div class="k-value">' + d.total +
          '</div><div class="k-sub">A 类 ' + aCount + " 个</div></div>" +
          '<div class="kpi green"><div class="k-label">在库数量</div><div class="k-value">' +
          F.wan(totalQty) + '</div><div class="k-sub">货值 ' + F.wan(totalVal) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">库存不足</div><div class="k-value">' + low +
          '</div><div class="k-sub">低于安全库存</div></div>' +
          '<div class="kpi"><div class="k-label">品类</div><div class="k-value">' + cats.length +
          '</div><div class="k-sub">' + F.esc(cats.slice(0, 3).join(" / ")) + "</div></div></div>" +
          F.chips([["", "全部品类"]].concat(cats.map(function (c) {
            return [c, c];
          })), cat, "data-cat") +
          F.chips([["", "全部"], ["A", "A 类"], ["B", "B 类"], ["C", "C 类"]], abc, "data-abc") +
          "</div></div>";

        html += '<div class="panel"><div class="panel-title">物料列表' +
          '<span class="panel-actions small muted">点击行查看批次与流水</span></div>' +
          "<div class='panel-body flush'>" + F.table([
            { label: "编码", render: function (r) { return F.tag(r.abc, r.abc === "A" ? "green" :
              (r.abc === "B" ? "blue" : "gold")) + ' <span class="mono">' + F.esc(r.code) + "</span>"; } },
            { label: "名称 / 规格", render: function (r) { return '<b class="small">' + F.esc(r.name) +
              '</b><div class="muted small">' + F.esc(r.spec) + "</div>"; } },
            { label: "品类", render: function (r) { return F.tag(r.category, "gray"); } },
            { label: "单位", render: function (r) { return F.esc(r.unit); } },
            { label: "库存", num: true, render: function (r) { return '<b>' + F.qty(r.stockQty) +
              "</b>"; } },
            { label: "安全库存", num: true, render: function (r) { return F.qty(r.safety); } },
            { label: "水位", render: function (r) { return F.tag(r.level); } },
            { label: "货位", num: true, render: function (r) { return r.locCount + " 个"; } },
            { label: "体积", num: true, render: function (r) { return F.num(r.cube * 1000, 1) + " L"; } },
            { label: "单价", num: true, render: function (r) { return F.num(r.price, 2); } }
          ], list, { click: function (r) { return r.code; }, empty: "没有匹配的物料" }) +
          "</div></div>";
        document.getElementById("view").innerHTML = html;

        F.bindRows(document, openItem);
        document.querySelectorAll("[data-cat]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("items", { cat: b.getAttribute("data-cat"), abc: abc, q: q });
          });
        });
        document.querySelectorAll("[data-abc]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("items", { abc: b.getAttribute("data-abc"), cat: cat, q: q });
          });
        });
        document.getElementById("itGo").addEventListener("click", function () {
          F.go("items", { q: document.getElementById("itQ").value.trim(), cat: cat, abc: abc });
        });
        document.getElementById("itNew").addEventListener("click", function () {
          editItem(null, cats);
        });

        F.setSide('<div class="side-block"><div class="hd">ABC 分类</div><div class="bd small muted" ' +
          'style="line-height:1.9">按库存金额降序累计占比：A ≤ 70%（重点管控、靠近拣货面），' +
          'B ≤ 90%，其余为 C。分类由系统按当前库存自动计算，可在基础设置里查看规则。</div></div>');
        F.setStatus("物料主数据 · " + d.total + " 个物料");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function openItem(code) {
      F.api("GET", "/api/items/" + code).then(function (v) {
        var html = '<div class="kpi-grid four">' +
          '<div class="kpi"><div class="k-label">在库数量</div><div class="k-value">' +
          F.qty(v.stockQty) + '</div><div class="k-sub">锁定 ' + F.qty(v.allocated) + " · 批次 " +
          v.lotCount + "</div></div>" +
          '<div class="kpi green"><div class="k-label">货值</div><div class="k-value">' +
          F.wan(v.stockQty * v.price) + '</div><div class="k-sub">单价 ' + F.num(v.price, 2) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">水位</div><div class="k-value" style="font-size:16px">' +
          F.tag(v.level) + '</div><div class="k-sub">安全 ' + F.qty(v.safety) + " · 补货点 " +
          F.qty(v.reorder) + "</div></div>" +
          '<div class="kpi"><div class="k-label">存放</div><div class="k-value" style="font-size:16px">' +
          F.esc(v.storage) + '</div><div class="k-sub">' + v.locCount + " 个货位</div></div></div>" +
          '<div class="kv-grid">' +
          F.kv("编码", '<span class="mono">' + F.esc(v.code) + "</span>") +
          F.kv("名称", F.esc(v.name)) +
          F.kv("规格", F.esc(v.spec || "—")) +
          F.kv("品类", F.esc(v.category)) +
          F.kv("条码", '<span class="mono small">' + F.esc(v.barcode || "—") + "</span>") +
          F.kv("尺寸（cm）", v.length + "×" + v.width + "×" + v.height) +
          F.kv("单件体积", F.num(v.cube * 1000, 1) + " L") +
          F.kv("重量", F.num(v.weight, 2) + " kg · 体积重 " + F.num(v.volWeight, 2) + " kg") +
          F.kv("保质期", v.shelfLife ? v.shelfLife + " 天" : "—") +
          F.kv("状态", F.tag(v.status)) + "</div>";

        html += '<div class="sub-title">库存批次</div>' + F.table([
          { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
          { label: "货位", render: function (r) { return '<span class="mono">' + F.esc(r.location) + "</span>"; } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "可用", num: true, render: function (r) { return F.qty(r.avail); } },
          { label: "有效期", render: function (r) { return r.expiry ? F.esc(r.expiry) + " " +
            F.tag(r.daysLeft + " 天", r.expiryLevel === "临期" ? "gold" : "gray") : "—"; } },
          { label: "库龄", num: true, render: function (r) { return r.ageDays + " 天"; } }
        ], v.stocks, { empty: "该物料暂无库存" });

        html += '<div class="sub-title">近期流水</div>' + F.table([
          { label: "时间", render: function (r) { return '<span class="mono small">' + F.esc(r.ts) + "</span>"; } },
          { label: "类型", render: function (r) { return F.tag(r.type, "blue"); } },
          { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.lot) + "</span>"; } },
          { label: "从 → 到", render: function (r) { return '<span class="mono small">' +
            F.esc(r.from_loc || "—") + " → " + F.esc(r.to_loc || "—") + "</span>"; } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "单据", render: function (r) { return F.esc(r.ref_no || "—"); } }
        ], v.recentMoves, { empty: "暂无流水" });

        F.dialogWide("物料 " + v.code + " · " + v.name, html,
          '<button class="btn" id="itEdit">编辑</button>' +
          '<button class="btn" data-close-foot="1">关闭</button>');
        document.querySelector("[data-close-foot]").addEventListener("click", F.closeDialog);
        document.getElementById("itEdit").addEventListener("click", function () {
          F.closeDialog(); editItem(v);
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function editItem(v, cats) {
      var isNew = !v;
      var body = '<div class="form-grid">' +
        '<label>编码<input id="imCode" value="' + F.esc(v ? v.code : "") + '"' +
        (isNew ? "" : " disabled") + "></label>" +
        '<label>名称<input id="imName" value="' + F.esc(v ? v.name : "") + '"></label>' +
        '<label>规格<input id="imSpec" value="' + F.esc(v ? v.spec : "") + '"></label>' +
        '<label>品类<input id="imCat" value="' + F.esc(v ? v.category : "电子元件") + '" list="catList">' +
        '<datalist id="catList">' + (cats || []).map(function (c) {
          return '<option value="' + F.esc(c) + '">';
        }).join("") + "</datalist></label>" +
        '<label>单位<input id="imUnit" value="' + F.esc(v ? v.unit : "件") + '"></label>' +
        '<label>ABC<select id="imAbc">' + ["A", "B", "C"].map(function (x) {
          return '<option' + (v && v.abc === x ? " selected" : "") + ">" + x + "</option>";
        }).join("") + "</select></label>" +
        '<label>长 cm<input id="imL" type="number" value="' + (v ? v.length : 20) + '"></label>' +
        '<label>宽 cm<input id="imW" type="number" value="' + (v ? v.width : 15) + '"></label>' +
        '<label>高 cm<input id="imH" type="number" value="' + (v ? v.height : 10) + '"></label>' +
        '<label>重量 kg<input id="imWt" type="number" step="0.01" value="' +
        (v ? v.weight : 0.5) + '"></label>' +
        '<label>单价<input id="imPrice" type="number" step="0.01" value="' +
        (v ? v.price : 0) + '"></label>' +
        '<label>安全库存<input id="imSafety" type="number" value="' + (v ? v.safety : 0) + '"></label>' +
        '<label>保质期（天）<input id="imLife" type="number" value="' +
        (v ? v.shelfLife : 0) + '"></label>' +
        '<label>存放条件<select id="imStorage">' + ["常温", "冷藏", "冷冻"].map(function (x) {
          return '<option' + (v && v.storage === x ? " selected" : "") + ">" + x + "</option>";
        }).join("") + "</select></label>" +
        "</div>";
      F.dialog(isNew ? "新建物料" : "编辑物料 " + v.code, body,
        '<button class="btn primary" id="imOk">保存</button>');
      document.getElementById("imOk").addEventListener("click", function () {
        var payload = {
          name: document.getElementById("imName").value.trim(),
          spec: document.getElementById("imSpec").value.trim(),
          category: document.getElementById("imCat").value.trim(),
          unit: document.getElementById("imUnit").value.trim(),
          abc: document.getElementById("imAbc").value,
          length: Number(document.getElementById("imL").value || 0),
          width: Number(document.getElementById("imW").value || 0),
          height: Number(document.getElementById("imH").value || 0),
          weight: Number(document.getElementById("imWt").value || 0),
          price: Number(document.getElementById("imPrice").value || 0),
          safety: Number(document.getElementById("imSafety").value || 0),
          shelfLife: Number(document.getElementById("imLife").value || 0),
          storage: document.getElementById("imStorage").value
        };
        var req = isNew
          ? F.api("POST", "/api/items", Object.assign({ code: document.getElementById("imCode").value.trim().toUpperCase() }, payload))
          : F.api("PUT", "/api/items/" + v.code, payload);
        req.then(function () {
          F.closeDialog();
          F.toast(isNew ? "物料已创建" : "物料已更新", "ok");
          F.go("items", {});
          F.boot();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }
    load();
  });

  /* ============================================================ 往来单位 */
  F.register("partners", function (params) {
    var tab = params.tab || "suppliers";

    function load() {
      var api = tab === "customers" ? "/api/customers"
        : (tab === "carriers" ? "/api/carriers" : "/api/suppliers");
      F.api("GET", api).then(function (d) {
        var list = d.list || [];
        var html = '<div class="panel"><div class="panel-title">往来单位' +
          '<span class="panel-actions">' +
          '<button class="btn sm primary" id="pnNew">新建' +
          (tab === "customers" ? "客户" : (tab === "carriers" ? "承运商" : "供应商")) +
          "</button></span></div><div class=\"panel-body\">" +
          F.chips([["suppliers", "供应商", tab === "suppliers" ? list.length : ""],
            ["customers", "客户", tab === "customers" ? list.length : ""],
            ["carriers", "承运商", tab === "carriers" ? list.length : ""]], tab, "data-tab") +
          "</div></div>";

        html += '<div class="panel"><div class="panel-title">' +
          (tab === "customers" ? "客户" : (tab === "carriers" ? "承运商" : "供应商")) +
          "</div><div class='panel-body flush' id='pnBody'></div></div>";
        document.getElementById("view").innerHTML = html;
        var body = document.getElementById("pnBody");

        if (tab === "suppliers") {
          body.innerHTML = F.table([
            { label: "编码", render: function (r) { return '<span class="mono">' + F.esc(r.code) + "</span>"; } },
            { label: "名称", render: function (r) { return '<b>' + F.esc(r.name) + "</b>"; } },
            { label: "联系人", render: function (r) { return F.esc(r.contact); } },
            { label: "电话", render: function (r) { return '<span class="mono small">' + F.esc(r.phone) + "</span>"; } },
            { label: "交期", num: true, render: function (r) { return r.lead_days + " 天"; } },
            { label: "等级", render: function (r) { return F.tag(r.level, r.level === "A" ? "green" : "gray"); } },
            { label: "到货单", num: true, render: function (r) { return r.asnCount + " 单"; } },
            { label: "在途", num: true, render: function (r) { return r.openAsn ? F.tag(r.openAsn, "gold") : "—"; } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], list, { empty: "暂无供应商" });
        } else if (tab === "customers") {
          body.innerHTML = F.table([
            { label: "编码", render: function (r) { return '<span class="mono">' + F.esc(r.code) + "</span>"; } },
            { label: "名称", render: function (r) { return '<b>' + F.esc(r.name) + "</b>"; } },
            { label: "联系人", render: function (r) { return F.esc(r.contact); } },
            { label: "电话", render: function (r) { return '<span class="mono small">' + F.esc(r.phone) + "</span>"; } },
            { label: "等级", render: function (r) { return F.tag(r.level, r.level === "战略" ? "green" :
              (r.level === "重点" ? "blue" : "gray")); } },
            { label: "默认承运", render: function (r) { return F.esc(r.carrier); } },
            { label: "订单数", num: true, render: function (r) { return r.orderCount; } },
            { label: "在途", num: true, render: function (r) { return r.openOrder ? F.tag(r.openOrder, "gold") : "—"; } },
            { label: "累计金额", num: true, render: function (r) { return F.wan(r.amount); } }
          ], list, { empty: "暂无客户" });
        } else {
          body.innerHTML = F.table([
            { label: "编码", render: function (r) { return '<span class="mono">' + F.esc(r.code) + "</span>"; } },
            { label: "名称", render: function (r) { return '<b>' + F.esc(r.name) + "</b>"; } },
            { label: "运输方式", render: function (r) { return F.tag(r.mode, r.mode === "冷链" ? "blue" : "gray"); } },
            { label: "截单时间", render: function (r) { return '<span class="mono">' + F.esc(r.cutoff) + "</span>"; } },
            { label: "电话", render: function (r) { return '<span class="mono small">' + F.esc(r.phone) + "</span>"; } },
            { label: "发运单量", num: true, render: function (r) { return r.shipCount; } },
            { label: "运费合计", num: true, render: function (r) { return F.num(r.cost, 0); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], list, { empty: "暂无承运商" });
        }

        document.querySelectorAll("[data-tab]").forEach(function (b) {
          b.addEventListener("click", function () {
            F.go("partners", { tab: b.getAttribute("data-tab") });
          });
        });
        document.getElementById("pnNew").addEventListener("click", function () {
          if (tab === "customers") {
            F.dialog("新建客户",
              '<div class="form-grid">' +
              '<label>编码<input id="pcCode" placeholder="CUS-011"></label>' +
              '<label>名称<input id="pcName"></label>' +
              '<label>联系人<input id="pcContact"></label>' +
              '<label>电话<input id="pcPhone"></label>' +
              '<label>等级<select id="pcLevel"><option>普通</option><option>重点</option>' +
              "<option>战略</option></select></label>" +
              '<label>默认承运商<input id="pcCarrier" value="CR-01"></label></div>',
              '<button class="btn primary" id="pcOk">创建</button>');
            document.getElementById("pcOk").addEventListener("click", function () {
              F.api("POST", "/api/customers", {
                code: document.getElementById("pcCode").value.trim(),
                name: document.getElementById("pcName").value.trim(),
                contact: document.getElementById("pcContact").value.trim(),
                phone: document.getElementById("pcPhone").value.trim(),
                level: document.getElementById("pcLevel").value,
                carrier: document.getElementById("pcCarrier").value.trim()
              }).then(function () {
                F.closeDialog(); F.toast("客户已创建", "ok");
                F.go("partners", { tab: "customers" }); F.boot();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          } else if (tab === "carriers") {
            F.dialog("新建承运商",
              '<div class="form-grid">' +
              '<label>编码<input id="prCode" placeholder="CR-06"></label>' +
              '<label>名称<input id="prName"></label>' +
              '<label>运输方式<select id="prMode"><option>公路</option><option>冷链</option>' +
              "<option>航空</option><option>铁路</option></select></label>" +
              '<label>截单时间<input id="prCut" type="time" value="18:00"></label>' +
              '<label>电话<input id="prPhone"></label></div>',
              '<button class="btn primary" id="prOk">创建</button>');
            document.getElementById("prOk").addEventListener("click", function () {
              F.api("POST", "/api/carriers", {
                code: document.getElementById("prCode").value.trim(),
                name: document.getElementById("prName").value.trim(),
                mode: document.getElementById("prMode").value,
                cutoff: document.getElementById("prCut").value,
                phone: document.getElementById("prPhone").value.trim()
              }).then(function () {
                F.closeDialog(); F.toast("承运商已创建", "ok");
                F.go("partners", { tab: "carriers" }); F.boot();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          } else {
            F.dialog("新建供应商",
              '<div class="form-grid">' +
              '<label>编码<input id="psCode" placeholder="SUP-009"></label>' +
              '<label>名称<input id="psName"></label>' +
              '<label>联系人<input id="psContact"></label>' +
              '<label>电话<input id="psPhone"></label>' +
              '<label>交期（天）<input id="psLead" type="number" value="3"></label>' +
              '<label>等级<select id="psLevel"><option>B</option><option>A</option>' +
              "<option>C</option></select></label></div>",
              '<button class="btn primary" id="psOk">创建</button>');
            document.getElementById("psOk").addEventListener("click", function () {
              F.api("POST", "/api/suppliers", {
                code: document.getElementById("psCode").value.trim(),
                name: document.getElementById("psName").value.trim(),
                contact: document.getElementById("psContact").value.trim(),
                phone: document.getElementById("psPhone").value.trim(),
                leadDays: Number(document.getElementById("psLead").value || 3),
                level: document.getElementById("psLevel").value
              }).then(function () {
                F.closeDialog(); F.toast("供应商已创建", "ok");
                F.go("partners", { tab: "suppliers" }); F.boot();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          }
        });
        F.setStatus("往来单位 · " + list.length + " 条记录");
        F.setSide('<div class="side-block"><div class="hd">说明</div><div class="bd small muted" ' +
          'style="line-height:1.9">供应商交期用于预约到货建议；客户等级影响出库优先级排序；' +
          '承运商截单时间用于准时发运率统计与波次分组。</div></div>');
      }).catch(function (e) { F.toast(e.message, "err"); });
    }
    load();
  });
})(window, document);
