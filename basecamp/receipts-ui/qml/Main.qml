import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "pramana.js" as PR

// Pramana for Logos Basecamp: the same app as adb3502.github.io/pramana-protocol, native QML.
// Data: the evidence graph snapshot (published on Logos Storage) bundled with this module and mirrored
// into the `receipts` core module's SQLite store. Search: Claude Sonnet through the Pramana relay.
Item {
    id: root
    width: 1280; height: 820

    // tokens (same as the web app)
    readonly property color chrome: "#f7f7f5"
    readonly property color bg: "#ffffff"
    readonly property color hover: "#f2f3f0"
    readonly property color sel: "#eef2ec"
    readonly property color ink: "#1a1d1b"
    readonly property color t2: "#454c47"
    readonly property color t3: "#646b66"
    readonly property color t4: "#8a908b"
    readonly property color line: "#e5e6e2"
    readonly property color line2: "#d6d8d3"
    readonly property color primary: "#18301f"
    readonly property color mark: "#f7d678"
    readonly property color diff: "#b42318"
    readonly property color okc: "#2e6b45"
    readonly property color lowerc: "#2f6c8f"
    readonly property color higherc: "#b5652b"
    readonly property color nullc: "#a3a9a4"
    readonly property string mono: "JetBrains Mono, DejaVu Sans Mono, Menlo, Consolas, monospace"

    property bool ready: false
    property var cnt: ({})
    property var route: ({v: "home"})
    property var history: []
    property bool raw: false          // lens toggle: Raw data hides lens labels
    property var drawer: null         // paper detail panel
    property var searches: ({})       // q -> {status, plan, err, sum, sumErr, busy}
    property int tick: 0              // bump to refresh bindings that read `searches`
    property string coreNote: ""

    function go(r) { history.push(route); route = r; if (pageFlick) pageFlick.contentY = 0; drawer = null }
    function back() { if (history.length) { route = history.pop(); drawer = null } }
    function search(q) { q = (q || "").trim(); if (!q) return; go({v: "search", q: q}); runSearch(q) }
    function openPaper(si) { drawer = PR.paperDetail(si) }
    function openPaperId(id) { const si = PR.sIndex[id]; if (si != null) openPaper(si) }
    function st(q) { tick; return searches[q] || {} }
    function setSt(q, o) { const s = searches; s[q] = Object.assign({}, s[q] || {}, o); searches = s; tick++ }

    // Claude runs through the receipts core module (sandboxed QML modules have no network); jobs are polled.
    property var jobs: ({})
    function claude(prompt, maxTokens, onText, done) {
        const id = parse(call("receipts", "askStart", [prompt, String(maxTokens)]), null)
        if (id === null || id === undefined || id === "") { PR.claude(prompt, maxTokens, onText, done); return }
        jobs[String(id)] = {onText: onText, done: done, last: ""}; poller.start()
    }
    Timer { id: poller; interval: 350; repeat: true
        onTriggered: { let live = 0
            for (const id in root.jobs) { const j = root.jobs[id]; const r = root.parse(root.call("receipts", "askPoll", [id]), {done: true, error: "no response from the core module", text: ""})
                if (r.text !== j.last) { j.last = r.text; if (j.onText) j.onText(r.text) }
                if (r.done) { delete root.jobs[id]; j.done(r.text || "", r.error || null) } else live++ }
            if (!live) stop() } }

    function runSearch(q) {
        const cur = st(q); if (cur.status === "pending" || cur.status === "ok") return
        setSt(q, {status: "pending"})
        root.claude(PR.searchPrompt(q), 1500, null, function (text, err) {
            const plan = err ? null : PR.parseJSONLoose(text)
            if (!plan) { setSt(q, {status: "err", err: err || "Claude did not return the expected format. Try again."}); return }
            setSt(q, {status: "ok", plan: plan}); runSummary(q)
        })
    }
    function runSummary(q) {
        const s = st(q); const res = PR.retrieve(q, s.plan)
        setSt(q, {sum: "", busy: true})
        root.claude(PR.summaryPrompt(q, res, s.plan), 1200, function (t) { setSt(q, {sum: t}) },
                  function (t, err) { setSt(q, {sum: t, busy: false, sumErr: err || ""}) })
    }

    // ── Logos core module bridge (stats, CID, SQLite mirror) ─────────────
    function call(module, method, args) {
        if (typeof logos === "undefined" || !logos.callModule) return null
        try { return logos.callModule(module, method, args) } catch (e) { return null }
    }
    function parse(raw, fb) { if (raw === null || raw === undefined) return fb; try { const i = (typeof raw === "string") ? JSON.parse(raw) : raw; return (typeof i === "string") ? JSON.parse(i) : i } catch (e) { return fb } }

    Component.onCompleted: {
        PR.init(); cnt = PR.counts(); ready = true
        const info = parse(call("receipts", "stats", []), null)
        if (info && !info.studies) {
            const tries = ["/tmp/pramana_snapshot.json", "/tmp/pramana_snapshot_v2.json"]
            for (let i = 0; i < tries.length; i++) { const r = parse(call("receipts", "loadSnapshot", [tries[i]]), {}); if (r.studies) break }
        }
        call("receipts", "setSnapshotCid", [PR.CID])
        coreNote = info ? "receipts core module connected" : "core module not reachable; bundled snapshot in use"
    }


    Rectangle { anchors.fill: parent; color: root.bg }

    // ── components ──────────────────────────────────────────────────────
    component Btn: Rectangle {
        id: b
        property string text: ""
        property bool primaryStyle: false
        property bool small: false
        signal clicked()
        implicitWidth: bt.implicitWidth + (small ? 16 : 24); implicitHeight: small ? 26 : 32
        radius: 6; color: primaryStyle ? root.primary : (ma.containsMouse ? root.hover : root.bg)
        border.color: primaryStyle ? root.primary : root.line2
        Text { id: bt; anchors.centerIn: parent; text: b.text; color: b.primaryStyle ? "#ffffff" : root.ink; font.pixelSize: b.small ? 12 : 13 }
        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: b.clicked() }
    }
    component Chip: Rectangle {
        property string text: ""
        property color fill: root.chrome
        implicitWidth: ct.implicitWidth + 12; implicitHeight: 20; radius: 4; color: fill; border.color: root.line2
        Text { id: ct; anchors.centerIn: parent; text: parent.text; font.pixelSize: 12; color: root.t2 }
    }
    component H2: RowLayout {
        property string text: ""
        property string sub: ""
        Layout.fillWidth: true; Layout.topMargin: 20
        Text { text: parent.text; font.pixelSize: 14; font.weight: Font.DemiBold; color: root.ink }
        Text { text: parent.sub; font.pixelSize: 13; color: root.t3; Layout.fillWidth: true }
    }
    component Crumbs: Row {
        property var items: []   // [label, route|null]
        spacing: 6
        Repeater {
            model: parent.items
            delegate: Row {
                spacing: 6
                Text { text: modelData[0]; font.pixelSize: 13; color: modelData[1] ? root.t3 : root.ink; font.underline: cm.containsMouse
                       MouseArea { id: cm; anchors.fill: parent; enabled: !!modelData[1]; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go(modelData[1]) } }
                Text { visible: index < parent.parent.items.length - 1; text: "/"; color: root.t4; font.pixelSize: 13 }
            }
        }
    }
    component DirBar: Row {
        property var p: ({lower: 0, nul: 0, higher: 0, noci: 0})
        property real tot: Math.max(1, p.lower + p.nul + p.higher + p.noci)
        width: 420; height: 6
        Rectangle { width: parent.width * parent.p.lower / parent.tot; height: 6; color: root.lowerc }
        Rectangle { width: parent.width * parent.p.nul / parent.tot; height: 6; color: root.nullc }
        Rectangle { width: parent.width * parent.p.higher / parent.tot; height: 6; color: root.higherc }
        Rectangle { width: parent.width * parent.p.noci / parent.tot; height: 6; color: root.line2 }
    }
    component Legend: Flow {
        property var items: [[root.lowerc, "lower, interval excludes no effect"], [root.nullc, "interval includes no effect"], [root.higherc, "higher, interval excludes no effect"]]
        Layout.fillWidth: true; spacing: 12
        Repeater { model: parent.items; delegate: Row { spacing: 5; Rectangle { width: 8; height: 8; radius: 2; color: modelData[0]; anchors.verticalCenter: parent.verticalCenter } Text { text: modelData[1]; font.pixelSize: 12; color: root.t3 } } }
    }
    component PairRow: Rectangle {
        property var p
        Layout.fillWidth: true; implicitHeight: pc.implicitHeight + 20; color: pm.containsMouse ? root.hover : "transparent"
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
        ColumnLayout {
            id: pc; anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.leftMargin: 2; spacing: 6
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; font.weight: Font.DemiBold; color: root.ink
                   text: PR.esc(p.xl) + "<font color='#8a908b'>  →  </font>" + PR.esc(p.yl) }
            Text { textFormat: Text.StyledText; font.pixelSize: 13; color: root.t3
                   text: "<b>" + p.studies + "</b> " + (p.studies === 1 ? "study" : "studies") + "    <b>" + p.sources + "</b> " + (p.sources === 1 ? "source" : "sources") + "    <b>" + p.est + "</b> " + (p.est === 1 ? "estimate" : "estimates") }
            DirBar { p: parent.parent.p }
        }
        MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: "pair", x: p.x, y: p.y}) }
    }
    component ClaimRow: Rectangle {
        property var c
        property bool showPaper: true
        Layout.fillWidth: true; implicitHeight: cc.implicitHeight + 18; color: "transparent"
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
        ColumnLayout {
            id: cc; anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 3
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; color: root.ink
                   text: "<font color='#454c47' style='font-size:11px'>[" + PR.esc(c.kind) + "]</font>  " + PR.esc(c.text) }
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 12; color: root.t3
                   text: (showPaper ? "<a href='p'>" + PR.esc(c.title) + "</a> · " : "") + PR.esc(c.section) + (showPaper ? " · " + PR.esc(c.id) : "")
                   linkColor: root.t3; onLinkActivated: root.openPaper(c.si)
                   HoverHandler { cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor } }
        }
    }
    component Cell: Text {
        property real w: 100
        Layout.preferredWidth: w; Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 13; color: root.ink; elide: Text.ElideRight
    }
    component ValueMark: Rectangle {
        property string v: ""
        implicitWidth: vt.implicitWidth + 8; implicitHeight: 18; radius: 3; color: root.mark
        Text { id: vt; anchors.centerIn: parent; text: parent.v; font.family: root.mono; font.pixelSize: 12 }
    }

    // receipt card (single claim or multi-source comparison)
    component Receipt: Rectangle {
        id: rc
        property var r
        Layout.fillWidth: true; Layout.maximumWidth: 900
        implicitHeight: rcol.implicitHeight + 2; color: "#fffefb"; border.color: root.line2; radius: 8
        ColumnLayout {
            id: rcol; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 1; spacing: 0
            Rectangle { Layout.fillWidth: true; implicitHeight: hd.implicitHeight + 24; color: "transparent"
                RowLayout { id: hd; anchors.fill: parent; anchors.margins: 12; spacing: 12
                    ColumnLayout { Layout.fillWidth: true; spacing: 4
                        Text { text: (r.sources ? "Comparison · " + r.sources.length + " published answers" : r.kind + " · " + r.speaker + (r.date ? " · " + r.date : "")).toUpperCase(); font.pixelSize: 11; font.letterSpacing: 0.6; color: root.t3 }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: r.sources ? r.quote : "“" + r.quote + "”"; font.pixelSize: 17; font.weight: Font.DemiBold; color: root.ink } }
                    Text { text: r.id; font.family: root.mono; font.pixelSize: 12; color: root.t3; Layout.alignment: Qt.AlignTop } } }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line }
            // cited source
            ColumnLayout { visible: !r.sources; Layout.fillWidth: true; Layout.margins: 12; spacing: 2
                Text { text: "Cited source" + (root.raw ? "" : " · traceability: " + ["none", "vague", "identifiable", "direct link"][r.trace || 0]); font.pixelSize: 12; color: root.t3 }
                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; color: root.primary; linkColor: root.primary
                       text: r.cited_id && PR.sIndex[r.cited_id] != null ? "<a href='p'>" + PR.esc(r.cited) + "</a>" : PR.esc(r.cited)
                       onLinkActivated: root.openPaperId(r.cited_id) } }
            Rectangle { visible: !r.sources; Layout.fillWidth: true; height: 1; color: root.line }
            // field table
            GridLayout {
                Layout.fillWidth: true; Layout.margins: 12; columnSpacing: 14; rowSpacing: 8
                columns: r.sources ? r.sources.length + 1 : 3
                Text { text: r.sources ? "" : "Field"; font.pixelSize: 12; color: root.t3; Layout.preferredWidth: 110 }
                Repeater { model: r.sources ? r.sources : ["Source reports", "Claim says"]
                    delegate: ColumnLayout { Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 1
                        Text { text: typeof modelData === "string" ? modelData : modelData.name; font.pixelSize: 12; font.weight: Font.DemiBold; color: root.t2; Layout.fillWidth: true; wrapMode: Text.Wrap }
                        Text { visible: typeof modelData !== "string"; text: modelData.sub || ""; font.pixelSize: 11; color: root.t3; Layout.fillWidth: true; wrapMode: Text.Wrap } } }
                // comparison: answer row
                Text { visible: !!r.sources; text: "Answer"; font.pixelSize: 13; font.weight: Font.DemiBold; color: root.ink }
                Repeater { model: r.sources || []
                    delegate: ColumnLayout { Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 2
                        ValueMark { v: modelData.num } Text { text: modelData.unit; font.pixelSize: 12; color: root.t3; Layout.fillWidth: true; wrapMode: Text.Wrap } } }
                Repeater {
                    model: r.fields
                    delegate: Repeater {
                        property var f: modelData
                        model: r.sources ? f.length : 3
                        delegate: ColumnLayout {
                            Layout.fillWidth: index > 0; Layout.preferredWidth: index > 0 ? 1 : 110; spacing: 3
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: f[index]; font.pixelSize: index === 0 ? 12.5 : 13; font.weight: index === 0 ? Font.DemiBold : Font.Normal; color: root.ink }
                            Rectangle { visible: !r.sources && index === 2 && !root.raw; implicitWidth: lt.implicitWidth + 10; implicitHeight: 18; radius: 3
                                color: f[3] === "same" ? "#e6f0ea" : f[3] === "unverifiable" ? root.chrome : "#fbe9e7"
                                Text { id: lt; anchors.centerIn: parent; text: PR.lensLabel(f[3]); font.pixelSize: 11; color: f[3] === "same" ? root.okc : f[3] === "unverifiable" ? root.t3 : root.diff }
                                ToolTip.visible: lh.hovered; ToolTip.text: PR.lensRule(f[3]); HoverHandler { id: lh } }
                        }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line }
            RowLayout { visible: !!r.sources || !root.raw; Layout.fillWidth: true; Layout.margins: 12
                Text { text: r.sources ? "Spread, highest to lowest" : "Fields that differ"; font.pixelSize: 13; color: root.t2; Layout.fillWidth: true }
                Text { text: r.sources ? r.spread : PR.diffCount(r) + " of " + r.fields.length; font.family: root.mono; font.pixelSize: 15; font.weight: Font.DemiBold; color: r.sources ? root.ink : root.diff } }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line }
            ColumnLayout { Layout.fillWidth: true; Layout.margins: 12; spacing: 8
                Text { visible: !!r.summary; Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 14; color: root.ink; text: r.summary || "" }
                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; color: root.ink; text: "<b>" + (r.sources ? "Underlying paper." : "What the source found.") + "</b> " + PR.esc(r.found) }
                Text { visible: !!r.graph; Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 14; color: root.ink; text: r.graph || "" }
                Text { visible: !r.sources && !root.raw; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; color: root.ink; text: "<b>Lens note.</b> " + PR.esc(r.verdict || "") }
                Text { visible: !r.sources && !root.raw && !!r.beyond; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; color: root.ink; text: "<b>Beyond the source.</b> " + PR.esc(r.beyond || "") } }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line }
            Text { Layout.fillWidth: true; Layout.margins: 12; wrapMode: Text.Wrap; font.pixelSize: 12; color: root.t3
                   text: root.raw ? "Raw data: reported values only, no lens applied." : "Interpreted with " + PR.LENS.name + " · " + PR.LENS.author + (r.checked ? "  ·  Checked " + r.checked : "") }
        }
    }

    // force-directed graph on a Canvas: drag nodes, drag background to pan, wheel to zoom, click to open
    component GraphView: Rectangle {
        id: gv
        property var g: null
        property real gx: 0.04
        property real gy: 0.06
        property real zoom: 1
        property real ox: 0
        property real oy: 0
        property var hoverNode: null
        property string note: "Drag to move, scroll to zoom"
        signal nodeClicked(var n)
        Layout.fillWidth: true; implicitHeight: 420; radius: 8; border.color: root.line; color: "#fcfcfb"; clip: true
        onGChanged: { if (g) { PR.layoutInit(g); zoom = 1; ox = 0; oy = 0; sim.start() } cv.requestPaint() }
        Timer { id: sim; interval: 16; repeat: true; onTriggered: { let more = false; for (let i = 0; i < 4; i++) more = PR.layoutTick(gv.g, gv.gx, gv.gy) || more; if (!more) { stop(); gv.fit() } cv.requestPaint() } }
        function fit() { if (!g || !g.nodes.length) return; let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9
            for (const n of g.nodes) { x0 = Math.min(x0, n.x - n.r); y0 = Math.min(y0, n.y - n.r); x1 = Math.max(x1, n.x + n.r + (n.label ? 7 * Math.min(n.label.length, 40) : 0)); y1 = Math.max(y1, n.y + n.r) }
            zoom = Math.max(.2, Math.min(1.6, (width - 40) / Math.max(1, x1 - x0), (height - 40) / Math.max(1, y1 - y0))); ox = -(x0 + x1) / 2 * zoom; oy = -(y0 + y1) / 2 * zoom }
        function toScreen(n) { return [width / 2 + ox + n.x * zoom, height / 2 + oy + n.y * zoom] }
        function hit(mx, my) { if (!g) return null; for (let i = g.nodes.length - 1; i >= 0; i--) { const n = g.nodes[i], p = toScreen(n), r = Math.max(6, n.r * zoom + 2); if ((mx - p[0]) * (mx - p[0]) + (my - p[1]) * (my - p[1]) <= r * r) return n } return null }
        Canvas {
            id: cv; anchors.fill: parent; renderStrategy: Canvas.Cooperative
            onPaint: {
                const c = getContext("2d"); c.reset(); c.clearRect(0, 0, width, height); const g = gv.g; if (!g) return
                c.save(); c.translate(width / 2 + gv.ox, height / 2 + gv.oy); c.scale(gv.zoom, gv.zoom)
                for (const l of g.links) { const s = g.nodes[l.si], t = g.nodes[l.ti]; c.globalAlpha = l.o || .8; c.strokeStyle = "#c9ccc7"; c.lineWidth = (l.w || 1) / gv.zoom * Math.min(gv.zoom, 1.5); c.beginPath(); c.moveTo(s.x, s.y); c.lineTo(t.x, t.y); c.stroke() }
                c.globalAlpha = 1
                for (const n of g.nodes) {
                    c.beginPath(); c.arc(n.x, n.y, n.r, 0, Math.PI * 2); c.fillStyle = n.fill; c.fill()
                    c.lineWidth = (n.sw || 1.5); c.strokeStyle = n === gv.hoverNode ? "#18301f" : (n.stroke || "#ffffff"); c.stroke()
                    if (n.label) { c.fillStyle = "#1a1d1b"; c.font = "12px sans-serif"; c.fillText(n.label, n.x + n.r + 4, n.y + 4) }
                }
                c.restore()
            }
        }
        MouseArea {
            anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton
            property var dn: null
            property real px: 0
            property real py: 0
            property bool moved: false
            cursorShape: gv.hoverNode && gv.hoverNode.kind !== "q" ? Qt.PointingHandCursor : (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor)
            onPressed: (e) => { dn = gv.hit(e.x, e.y); px = e.x; py = e.y; moved = false; if (dn) { dn.drag = true; gv.g.alpha = Math.max(gv.g.alpha, .2); sim.start() } }
            onPositionChanged: (e) => {
                if (pressed) { const dx = e.x - px, dy = e.y - py; if (Math.abs(dx) + Math.abs(dy) > 2) moved = true
                    if (dn) { dn.x += dx / gv.zoom; dn.y += dy / gv.zoom; gv.g.alpha = Math.max(gv.g.alpha, .1); if (!sim.running) sim.start() } else { gv.ox += dx; gv.oy += dy }
                    px = e.x; py = e.y; cv.requestPaint() }
                else { const h = gv.hit(e.x, e.y); if (h !== gv.hoverNode) { gv.hoverNode = h; cv.requestPaint() } tip.x = Math.min(e.x + 14, gv.width - tip.width - 6); tip.y = Math.min(e.y + 14, gv.height - tip.height - 6) }
            }
            onReleased: (e) => { if (dn) { dn.drag = false; if (!moved) gv.nodeClicked(dn) } dn = null }
            onExited: { gv.hoverNode = null; cv.requestPaint() }
            onWheel: (w) => { const k = w.angleDelta.y > 0 ? 1.15 : 1 / 1.15, nz = Math.max(.2, Math.min(6, gv.zoom * k)); const cx = w.x - gv.width / 2 - gv.ox, cy = w.y - gv.height / 2 - gv.oy;
                gv.ox -= cx * (nz / gv.zoom - 1); gv.oy -= cy * (nz / gv.zoom - 1); gv.zoom = nz; cv.requestPaint() }
        }
        Rectangle { id: tip; visible: !!gv.hoverNode && !!gv.hoverNode.tip; width: Math.min(300, tt.implicitWidth + 16); height: tt.implicitHeight + 12; radius: 6; color: "#1a1d1b"; opacity: .94
            Text { id: tt; x: 8; y: 6; width: 284; wrapMode: Text.Wrap; color: "#ffffff"; font.pixelSize: 12; text: gv.hoverNode ? gv.hoverNode.tip : "" } }
        Column { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8; spacing: 4
            Repeater { model: [["+", 1.4], ["−", 1 / 1.4], ["⤢", 0]]
                delegate: Rectangle { width: 26; height: 26; radius: 5; color: root.bg; border.color: root.line2
                    Text { anchors.centerIn: parent; text: modelData[0]; font.pixelSize: 14; color: root.t2 }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { if (modelData[1]) gv.zoom = Math.max(.2, Math.min(6, gv.zoom * modelData[1])); else gv.fit(); cv.requestPaint() } } } } }
        Text { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 8; text: gv.note; font.pixelSize: 11; color: root.t4 }
    }

    // ── shell: top bar, sidebar, page, drawer ──────────────────────────
    ColumnLayout {
        anchors.fill: parent; spacing: 0
        // top bar
        Rectangle {
            Layout.fillWidth: true; implicitHeight: 48; color: root.chrome
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 12; spacing: 12
                Text { text: "Pramana"; font.pixelSize: 15; font.weight: Font.DemiBold; color: root.ink; Layout.preferredWidth: 172
                       MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: "home"}) } }
                Rectangle {
                    visible: root.route.v !== "home"
                    Layout.fillWidth: true; Layout.maximumWidth: 680; implicitHeight: 32; radius: 8; color: root.bg
                    border.color: topq.activeFocus ? root.primary : root.line2
                    RowLayout { anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 6; spacing: 8
                        Text { text: "⌕"; font.pixelSize: 16; color: root.t3 }
                        TextField { id: topq; Layout.fillWidth: true; background: null; font.pixelSize: 14; placeholderText: "Search a claim or question"
                                    text: root.route.v === "search" ? root.route.q : ""; onAccepted: root.search(text) } }
                }
                Item { Layout.fillWidth: true; visible: root.route.v === "home" }
                Item { Layout.fillWidth: true; visible: root.route.v !== "home" }
                // lens toggle
                Rectangle {
                    implicitWidth: segRow.implicitWidth + 4; implicitHeight: 30; radius: 8; border.color: root.line2; color: root.bg
                    Row { id: segRow; anchors.centerIn: parent; spacing: 0
                        Repeater { model: [["Pramana lens v1", false], ["Raw data", true]]
                            delegate: Rectangle { width: sl.implicitWidth + 20; height: 26; radius: 6; color: root.raw === modelData[1] ? root.primary : "transparent"
                                Text { id: sl; anchors.centerIn: parent; text: modelData[0]; font.pixelSize: 13; color: root.raw === modelData[1] ? "#ffffff" : root.t2 }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.raw = modelData[1] } } } }
                }
                Rectangle { implicitWidth: aiL.implicitWidth + 16; implicitHeight: 30; radius: 8; border.color: root.line2; color: root.bg
                    Text { id: aiL; anchors.centerIn: parent; text: "Claude Sonnet"; font.pixelSize: 13; color: root.t2 } }
            }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            // sidebar
            Rectangle {
                Layout.preferredWidth: 200; Layout.fillHeight: true; color: root.chrome
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: root.line }
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 8; anchors.topMargin: 10; spacing: 1
                    Repeater {
                        model: [["Search", "home", ""], ["Receipts", "receipts", String(root.cnt.receipts || "")], ["Evidence map", "map", PR.fmt(root.cnt.pairs || 0)], ["Paper network", "network", ""], ["About", "about", ""]]
                        delegate: Rectangle {
                            property bool cur: root.route.v === modelData[1] || (modelData[1] === "home" && root.route.v === "search") || (modelData[1] === "receipts" && root.route.v === "receipt") || (modelData[1] === "map" && root.route.v === "pair")
                            Layout.fillWidth: true; implicitHeight: 32; radius: 6; color: cur ? root.sel : (nm.containsMouse ? root.hover : "transparent")
                            Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; font.pixelSize: 14; color: cur ? root.primary : root.t2; font.weight: cur ? Font.DemiBold : Font.Normal }
                            Text { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData[2]; font.family: root.mono; font.pixelSize: 11; color: root.t3 }
                            MouseArea { id: nm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: modelData[1]}) }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Rectangle { Layout.fillWidth: true; height: 1; color: root.line }
                    ColumnLayout { Layout.margins: 10; spacing: 2
                        Text { textFormat: Text.StyledText; font.pixelSize: 12; color: root.t3; text: "<b><font color='#1a1d1b'>" + PR.fmt(root.cnt.papers || 0) + "</font></b> papers" }
                        Text { textFormat: Text.StyledText; font.pixelSize: 12; color: root.t3; text: "<b><font color='#1a1d1b'>" + PR.fmt(root.cnt.estimates || 0) + "</font></b> extracted estimates" }
                        Text { font.pixelSize: 12; color: root.t3; text: "Logos Storage " + PR.CID.slice(0, 10) + "…"; ToolTip.visible: ch.hovered; ToolTip.text: PR.CID; HoverHandler { id: ch } }
                        Text { font.pixelSize: 11; color: root.t4; text: root.coreNote; Layout.preferredWidth: 170; wrapMode: Text.Wrap }
                    }
                }
            }
            // page
            Flickable {
                id: pageFlick
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                contentWidth: width; contentHeight: pageLoader.item ? pageLoader.item.implicitHeight + 64 : 0
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                Loader {
                    id: pageLoader
                    x: root.route.v === "home" ? Math.max(24, (pageFlick.width - 760) / 2) : 24; y: root.route.v === "home" ? 56 : 16
                    width: root.route.v === "home" ? Math.min(760, pageFlick.width - 48) : Math.min(root.route.v === "network" ? 1400 : 1200, pageFlick.width - 48)
                    active: root.ready
                    sourceComponent: ({home: homePage, search: searchPage, receipts: receiptsPage, receipt: receiptPage, map: mapPage, pair: pairPage, paper: paperPage, network: networkPage, about: aboutPage})[root.route.v] || homePage
                }
            }
        }
    }
    // paper drawer
    Rectangle { anchors.fill: parent; color: "#000000"; opacity: root.drawer ? .18 : 0; visible: opacity > 0; Behavior on opacity { NumberAnimation { duration: 150 } }
        MouseArea { anchors.fill: parent; onClicked: root.drawer = null } }
    Rectangle {
        id: drawerPanel
        width: Math.min(560, root.width - 80); height: root.height; x: root.drawer ? root.width - width : root.width
        Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        color: root.bg; border.color: root.line
        Flickable {
            anchors.fill: parent; anchors.margins: 1; clip: true; contentHeight: dcol.implicitHeight + 40; ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: dcol; x: 20; y: 16; width: drawerPanel.width - 40; spacing: 8
                property var d: root.drawer || ({claims: [], flags: [], est: []})
                RowLayout { Layout.fillWidth: true
                    ColumnLayout { Layout.fillWidth: true; spacing: 2
                        Text { text: dcol.d.id || ""; font.family: root.mono; font.pixelSize: 12; color: root.t3 }
                        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: dcol.d.title || ""; font.pixelSize: 17; font.weight: Font.DemiBold; color: root.ink } }
                    Text { text: "×"; font.pixelSize: 22; color: root.t3; Layout.alignment: Qt.AlignTop; MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.drawer = null } } }
                GridLayout { columns: 2; columnSpacing: 16; rowSpacing: 4; Layout.fillWidth: true
                    Text { text: "Design"; color: root.t3; font.pixelSize: 13 } Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: dcol.d.design || ""; font.pixelSize: 13; color: root.ink }
                    Text { text: "Population"; color: root.t3; font.pixelSize: 13 } Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: dcol.d.population || ""; font.pixelSize: 13; color: root.ink }
                    Text { text: "Estimates"; color: root.t3; font.pixelSize: 13 } Text { text: PR.fmt(dcol.d.nEst || 0); font.family: root.mono; font.pixelSize: 13; color: root.ink } }
                Row { spacing: 8
                    Btn { text: "Open paper page"; primaryStyle: true; onClicked: { const si = dcol.d.si; root.go({v: "paper", si: si}) } }
                    Btn { visible: !!dcol.d.link; text: dcol.d.linkName || ""; onClicked: Qt.openUrlExternally(dcol.d.link) } }
                H2 { text: "What the authors concluded"; sub: String(dcol.d.claims.length) }
                Repeater { model: dcol.d.claims
                    delegate: Rectangle { Layout.fillWidth: true; implicitHeight: cx.implicitHeight + 16; radius: 6; color: root.chrome; border.color: root.line
                        ColumnLayout { id: cx; x: 10; y: 8; width: parent.width - 20; spacing: 3
                            Text { text: modelData.kind + " · " + modelData.section; font.pixelSize: 11; color: root.t3 }
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.text; font.pixelSize: 14; color: root.ink } } } }
                Text { visible: !dcol.d.claims.length; text: "None extracted."; color: root.t3; font.pixelSize: 13 }
                H2 { text: "Estimates"; sub: String(dcol.d.nEst || 0) }
                Repeater { model: (dcol.d.est || []).slice(0, 60)
                    delegate: Rectangle { Layout.fillWidth: true; implicitHeight: er.implicitHeight + 12; color: em.containsMouse ? root.hover : "transparent"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                        RowLayout { id: er; x: 2; y: 6; width: parent.width - 4; spacing: 10
                            ColumnLayout { Layout.fillWidth: true; spacing: 1
                                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.pair; font.pixelSize: 13; color: root.primary }
                                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.measure + (modelData.level ? " · " + modelData.level : ""); font.pixelSize: 11; color: root.t3 } }
                            ColumnLayout { spacing: 1; ValueMark { v: modelData.value; Layout.alignment: Qt.AlignRight } Text { text: modelData.ci; font.family: root.mono; font.pixelSize: 11; color: root.t3; Layout.alignment: Qt.AlignRight } } }
                        MouseArea { id: em; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: "pair", x: modelData.x, y: modelData.y}) } } }
                H2 { visible: !root.raw; text: "Bias flags"; sub: String(dcol.d.flags.length) }
                Repeater { model: root.raw ? [] : dcol.d.flags
                    delegate: Rectangle { Layout.fillWidth: true; implicitHeight: fx.implicitHeight + 16; radius: 6; color: root.chrome; border.color: root.line
                        ColumnLayout { id: fx; x: 10; y: 8; width: parent.width - 20; spacing: 3
                            Text { text: modelData.type + " · " + modelData.sev; font.pixelSize: 11; color: root.t3 }
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.note; font.pixelSize: 13; color: root.ink } } } }
            }
        }
    }

    // ── pages ───────────────────────────────────────────────────────────
    Component {
        id: homePage
        ColumnLayout {
            spacing: 0
            Text { text: "Search the evidence behind any claim"; font.pixelSize: 22; font.weight: Font.DemiBold; color: root.ink }
            Text { Layout.fillWidth: true; Layout.topMargin: 4; wrapMode: Text.Wrap; font.pixelSize: 14; color: root.t3
                   text: "Ask in plain words. Claude maps your question to " + PR.fmt(root.cnt.papers) + " papers read down to their reported estimates, then shows the papers, the numbers and how they connect." }
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 20; spacing: 8
                Rectangle { Layout.fillWidth: true; implicitHeight: 44; radius: 8; border.color: hq.activeFocus ? root.primary : root.line2; color: root.bg
                    TextField { id: hq; anchors.fill: parent; anchors.leftMargin: 8; background: null; font.pixelSize: 16; placeholderText: "Does coffee affect heart disease? How much water does AI use?"; onAccepted: root.search(text); Component.onCompleted: forceActiveFocus() } }
                Btn { text: "Search"; primaryStyle: true; implicitHeight: 44; implicitWidth: 96; onClicked: root.search(hq.text) } }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 16; height: 1; color: root.line }
            Repeater { model: PR.EX
                delegate: Rectangle { Layout.fillWidth: true; implicitHeight: 42; color: xm.containsMouse ? root.hover : "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                    Text { anchors.left: parent.left; anchors.leftMargin: 2; anchors.verticalCenter: parent.verticalCenter; text: modelData; font.pixelSize: 14; color: root.ink }
                    Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: "example"; font.pixelSize: 13; color: root.t3 }
                    MouseArea { id: xm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.search(modelData) } } }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 28; implicitHeight: 64; radius: 8; border.color: root.line; color: root.bg
                RowLayout { anchors.fill: parent; spacing: 0
                    Repeater { model: [[root.cnt.papers, "papers"], [root.cnt.sources, "independent sources"], [root.cnt.estimates, "estimates"], [root.cnt.pairs, "exposure and outcome pairs"]]
                        delegate: Item { Layout.fillWidth: true; Layout.fillHeight: true
                            Rectangle { visible: index > 0; width: 1; height: parent.height; color: root.line }
                            Column { x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                                Text { text: PR.fmt(modelData[0]); font.family: root.mono; font.pixelSize: 18; font.weight: Font.DemiBold; color: root.ink }
                                Text { text: modelData[1]; font.pixelSize: 13; color: root.t3 } } } } } }
            Flow { Layout.fillWidth: true; Layout.topMargin: 20; spacing: 8
                Btn { text: "Receipts"; onClicked: root.go({v: "receipts"}) }
                Btn { text: "Evidence map"; onClicked: root.go({v: "map"}) }
                Btn { text: "Paper network"; onClicked: root.go({v: "network"}) }
                Btn { text: "About the protocol"; onClicked: root.go({v: "about"}) }
                Btn { text: "Contribute papers"; onClicked: Qt.openUrlExternally("https://adb3502.github.io/pramana-protocol/contribute/") } }
        }
    }

    Component {
        id: searchPage
        ColumnLayout {
            id: sp
            spacing: 0
            property string q: root.route.q || ""
            property var s: root.st(q)
            property var plan: s.status === "ok" ? s.plan : null
            property var res: PR.retrieve(q, plan)
            property var rec: PR.matchCurated(q)
            property var fx: plan && plan.fields ? plan.fields : null
            Crumbs { items: [["Home", {v: "home"}], ["Search", null]] }
            Text { Layout.fillWidth: true; Layout.topMargin: 6; wrapMode: Text.Wrap; text: sp.q; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 14; color: root.t3
                   text: sp.plan && sp.plan.intent ? sp.plan.intent : PR.plural(sp.res.pairs.length, "exposure and outcome pair", "exposure and outcome pairs") + " and " + PR.plural(sp.res.papers.length, "paper", "papers") + " matched" }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 12; height: 1; color: root.line }
            // how the query was mapped
            Flow { Layout.fillWidth: true; Layout.topMargin: 10; spacing: 6
                BusyIndicator { visible: sp.s.status === "pending"; running: visible; width: 18; height: 18 }
                Text { font.pixelSize: 13; color: root.t3; height: 20; verticalAlignment: Text.AlignVCenter
                       text: sp.s.status === "pending" ? "Claude (Sonnet) is mapping your query to the database" : sp.plan ? "Mapped by Claude:" : "Matched by keywords." }
                Repeater { model: sp.plan ? (sp.plan.exposure_concepts || []).concat(sp.plan.outcome_concepts || []) : []; delegate: Chip { text: modelData } }
                Repeater { model: sp.plan ? (sp.plan.keywords || []) : []; delegate: Chip { text: modelData; fill: root.bg } }
                Text { visible: sp.s.status === "err"; text: sp.s.err || ""; color: root.diff; font.pixelSize: 13 }
                Btn { visible: sp.s.status === "err" || !sp.s.status; small: true; text: "Search with Claude"; onClicked: { root.setSt(sp.q, {status: ""}); root.runSearch(sp.q) } } }
            // parsed fields
            GridLayout { visible: !!sp.fx; Layout.fillWidth: true; Layout.topMargin: 10; columns: 6; columnSpacing: 0; rowSpacing: 0
                Repeater { model: sp.fx ? [["Subject", sp.fx.subject], ["Outcome", sp.fx.outcome], ["Relation", sp.fx.relation], ["Direction", sp.fx.direction], ["Population", sp.fx.population], ["Certainty", sp.fx.certainty]] : []
                    delegate: Rectangle { Layout.fillWidth: true; Layout.preferredWidth: 1; implicitHeight: fc.implicitHeight + 16; border.color: root.line; color: root.bg
                        Column { id: fc; x: 10; y: 8; width: parent.width - 20; spacing: 2
                            Text { text: modelData[0]; font.pixelSize: 12; color: root.t3 }
                            Text { width: parent.width; wrapMode: Text.Wrap; text: modelData[1] || "not stated"; font.pixelSize: 14; color: root.ink } } } } }
            // summary
            Rectangle { visible: sp.s.sum !== undefined; Layout.fillWidth: true; Layout.topMargin: 14; implicitHeight: smc.implicitHeight + 24; radius: 8; color: root.chrome; border.color: root.line
                ColumnLayout { id: smc; x: 14; y: 12; width: parent.width - 28; spacing: 6
                    Text { text: "Summary from the evidence · Claude reading of the records shown · lens: none"; font.pixelSize: 13; color: root.t3 }
                    Text { Layout.fillWidth: true; Layout.maximumWidth: 820; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 14; lineHeight: 1.15; color: root.ink; linkColor: root.primary
                           text: sp.s.sum ? PR.citeHtml(sp.s.sum) : "Claude is reading the records…"
                           onLinkActivated: (l) => root.openPaperId(l.replace("paper:", ""))
                           HoverHandler { cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor } }
                    Text { visible: !!sp.s.sumErr; text: sp.s.sumErr || ""; color: root.diff; font.pixelSize: 13 } } }
            // network + papers
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 4; spacing: 20
                ColumnLayout { Layout.fillWidth: true; Layout.preferredWidth: 3; Layout.alignment: Qt.AlignTop; spacing: 6
                    H2 { text: "Evidence network"; sub: PR.plural(sp.res.pairs.length, "pair", "pairs") + " · click a paper" }
                    Legend { items: [[PR.DHEX.lower, "lower"], [PR.DHEX["null"], "interval includes no effect"], [PR.DHEX.higher, "higher"], [PR.DHEX.noci, "no interval reported"]] }
                    GraphView { implicitHeight: 460; g: PR.evidenceGraph(sp.q, sp.res.pairs.slice(0, 8), sp.res.papers)
                        onNodeClicked: (n) => { if (n.kind === "paper") root.openPaper(n.si); else if (n.kind === "pair") root.go({v: "pair", x: n.x0, y: n.y0}) } } }
                ColumnLayout { Layout.fillWidth: true; Layout.preferredWidth: 2; Layout.alignment: Qt.AlignTop; spacing: 0
                    H2 { text: "Papers"; sub: PR.plural(sp.res.papers.length, "match", "matches") }
                    Item { implicitHeight: 6 }
                    Repeater { model: sp.res.papers.slice(0, 25).map(function (o) { return PR.paperVM(o.si) })
                        delegate: Rectangle { Layout.fillWidth: true; implicitHeight: prc.implicitHeight + 14; color: prm.containsMouse ? root.hover : "transparent"; radius: 4
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                            RowLayout { id: prc; x: 4; y: 7; width: parent.width - 8; spacing: 8
                                Rectangle { width: 9; height: 9; radius: 5; color: modelData.color; Layout.alignment: Qt.AlignTop; Layout.topMargin: 4 }
                                ColumnLayout { Layout.fillWidth: true; spacing: 2
                                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; text: modelData.title; font.pixelSize: 14; font.weight: Font.Medium; color: root.ink }
                                    Text { Layout.fillWidth: true; elide: Text.ElideRight; text: modelData.design.slice(0, 90) + " · " + modelData.id; font.pixelSize: 12; color: root.t3 } } }
                            MouseArea { id: prm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.openPaper(modelData.si) } } }
                    Text { visible: !sp.res.papers.length; text: "No paper matches."; color: root.t3; font.pixelSize: 14 } } }
            // receipt
            H2 { visible: !!sp.rec; text: "Published receipt"; sub: sp.rec ? sp.rec.id : "" }
            Loader { active: !!sp.rec; Layout.fillWidth: true; Layout.topMargin: 6; sourceComponent: Receipt { r: sp.rec } }
            H2 { text: "Exposure and outcome pairs"; sub: String(sp.res.pairs.length) }
            Legend { visible: sp.res.pairs.length > 0; Layout.topMargin: 4 }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line; Layout.topMargin: 6 }
            Repeater { model: sp.res.pairs.map(PR.pairVM); delegate: PairRow { p: modelData } }
            Text { visible: !sp.res.pairs.length; Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.t3; font.pixelSize: 14; text: "No exposure and outcome in the graph match. The graph covers " + root.cnt.corpus + "." }
            H2 { text: "Author conclusions"; sub: String(sp.res.claims.length) }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line; Layout.topMargin: 6 }
            Repeater { model: sp.res.claims.map(PR.claimVM); delegate: ClaimRow { c: modelData } }
        }
    }

    Component {
        id: receiptsPage
        ColumnLayout {
            spacing: 0
            Crumbs { items: [["Home", {v: "home"}], ["Receipts", null]] }
            Text { Layout.topMargin: 6; text: "Receipts"; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
            Text { text: "Published claims set beside the sources they cite. Each one has its own page."; font.pixelSize: 14; color: root.t3 }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 12; height: 1; color: root.line }
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 14; spacing: 10
                Cell { w: 500; text: "Claim"; color: root.t3; font.pixelSize: 12 } Cell { w: 160; text: "Speaker"; color: root.t3; font.pixelSize: 12 }
                Cell { w: 110; text: "Kind"; color: root.t3; font.pixelSize: 12 } Cell { visible: !root.raw; w: 150; text: "Fields that differ"; color: root.t3; font.pixelSize: 12 } }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line2; Layout.topMargin: 6 }
            Repeater { model: PR.CUR
                delegate: Rectangle { Layout.fillWidth: true; implicitHeight: rr.implicitHeight + 18; color: rm.containsMouse ? root.hover : "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                    RowLayout { id: rr; x: 0; y: 9; width: parent.width; spacing: 10
                        ColumnLayout { Layout.preferredWidth: 500; Layout.fillWidth: true; spacing: 2
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.quote; font.pixelSize: 14; color: root.ink }
                            Text { text: modelData.id; font.family: root.mono; font.pixelSize: 11; color: root.t3 } }
                        Cell { w: 160; text: modelData.speaker } Cell { w: 110; text: modelData.kind }
                        Cell { visible: !root.raw; w: 150; text: modelData.sources ? modelData.sources.length + " answers compared" : PR.diffCount(modelData) + " of " + modelData.fields.length; color: modelData.sources ? root.t3 : root.diff } }
                    MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: "receipt", id: modelData.id}) } } }
        }
    }

    Component {
        id: receiptPage
        ColumnLayout {
            id: rp
            spacing: 10
            property var r: PR.receiptById(root.route.id)
            property int i: PR.CUR.indexOf(r)
            Crumbs { items: [["Home", {v: "home"}], ["Receipts", {v: "receipts"}], [root.route.id, null]] }
            Loader { active: !!rp.r; Layout.fillWidth: true; sourceComponent: Receipt { r: rp.r } }
            Row { spacing: 8; Layout.topMargin: 6
                Btn { text: "Search this claim"; onClicked: root.search(rp.r.quote) }
                Btn { visible: rp.i > 0; text: "Previous"; onClicked: root.go({v: "receipt", id: PR.CUR[rp.i - 1].id}) }
                Btn { visible: rp.i < PR.CUR.length - 1; text: "Next"; onClicked: root.go({v: "receipt", id: PR.CUR[rp.i + 1].id}) } }
        }
    }

    Component {
        id: mapPage
        ColumnLayout {
            id: mp
            spacing: 0
            property string filter: ""
            property string key: "studies"
            property int dir: -1
            property var data: PR.mapRows(filter, key, dir)
            Crumbs { items: [["Home", {v: "home"}], ["Evidence map", null]] }
            Text { Layout.topMargin: 6; text: "Evidence map"; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
            Text { text: "Every exposure and outcome a study related. Open a row for its studies and estimates."; font.pixelSize: 14; color: root.t3 }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 12; height: 1; color: root.line }
            RowLayout { Layout.topMargin: 12; spacing: 12
                Rectangle { implicitWidth: 340; implicitHeight: 32; radius: 6; border.color: mf.activeFocus ? root.primary : root.line2
                    TextField { id: mf; anchors.fill: parent; background: null; font.pixelSize: 14; placeholderText: "Filter: coffee, stroke, water"; onTextChanged: mp.filter = text } }
                Text { text: PR.plural(mp.data.total, "pair", "pairs") + (mp.data.total > 300 ? ", first 300 shown" : ""); font.family: root.mono; font.pixelSize: 12; color: root.t3 } }
            Legend { Layout.topMargin: 10 }
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 8; spacing: 10
                Repeater { model: [["x", "Exposure", 260], ["y", "Outcome", 260], ["studies", "Studies", 70], ["sources", "Sources", 70], ["est", "Estimates", 80], ["", "Headline direction", 220]]
                    delegate: Text { Layout.preferredWidth: modelData[2]; Layout.fillWidth: modelData[2] > 200; font.pixelSize: 12; color: mp.key === modelData[0] ? root.ink : root.t3; font.weight: mp.key === modelData[0] ? Font.DemiBold : Font.Normal
                        text: modelData[1] + (mp.key === modelData[0] ? (mp.dir === 1 ? " ↑" : " ↓") : "")
                        MouseArea { anchors.fill: parent; enabled: !!modelData[0]; cursorShape: Qt.PointingHandCursor
                            onClicked: { const k = modelData[0]; mp.dir = mp.key === k ? -mp.dir : (k === "x" || k === "y" ? 1 : -1); mp.key = k } } } } }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line2; Layout.topMargin: 6 }
            Repeater { model: mp.data.rows
                delegate: Rectangle { Layout.fillWidth: true; implicitHeight: mr.implicitHeight + 14; color: mrm.containsMouse ? root.hover : "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                    RowLayout { id: mr; y: 7; width: parent.width; spacing: 10
                        Cell { w: 260; text: modelData.xl } Cell { w: 260; text: modelData.yl }
                        Text { Layout.preferredWidth: 70; text: modelData.studies; font.family: root.mono; font.pixelSize: 13 }
                        Text { Layout.preferredWidth: 70; text: modelData.sources; font.family: root.mono; font.pixelSize: 13 }
                        Text { Layout.preferredWidth: 80; text: modelData.est; font.family: root.mono; font.pixelSize: 13 }
                        DirBar { p: modelData; width: 220; Layout.preferredWidth: 220 } }
                    MouseArea { id: mrm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: "pair", x: modelData.x, y: modelData.y}) } } }
        }
    }

    Component {
        id: pairPage
        ColumnLayout {
            id: pp
            spacing: 0
            property var d: PR.pairDetail(root.route.x, root.route.y)
            Crumbs { items: [["Home", {v: "home"}], ["Evidence map", {v: "map"}], [pp.d ? pp.d.xl + " → " + pp.d.yl : "Pair", null]] }
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 6
                ColumnLayout { Layout.fillWidth: true; spacing: 4
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.StyledText; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink
                           text: pp.d ? PR.esc(pp.d.xl) + " <font color='#8a908b'>→</font> " + PR.esc(pp.d.yl) : "This pair is not in the snapshot." }
                    Text { visible: !!pp.d; font.pixelSize: 14; color: root.t3
                           text: pp.d ? PR.plural(pp.d.studies, "study", "studies") + " · " + PR.plural(pp.d.sources, "independent source", "independent sources") + " · " + PR.plural(pp.d.est, "estimate", "estimates") : "" } }
                Btn { visible: !!pp.d; text: "Search this pair"; onClicked: root.search(pp.d.xl + " " + pp.d.yl) } }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 12; height: 1; color: root.line }
            Legend { Layout.topMargin: 10 }
            DirBar { visible: !!pp.d; p: pp.d || ({lower: 0, nul: 0, higher: 0, noci: 0}); Layout.topMargin: 4 }
            H2 { text: "Papers on this pair"; sub: "click a paper" }
            GraphView { Layout.topMargin: 6; implicitHeight: 380; g: pp.d ? PR.evidenceGraph(pp.d.xl + " → " + pp.d.yl, [PR.pairIdx[root.route.x + "|" + root.route.y]], []) : null
                onNodeClicked: (n) => { if (n.kind === "paper") root.openPaper(n.si) } }
            H2 { text: "Estimates"; sub: pp.d ? PR.plural(pp.d.rows.length, "row", "rows") : "" }
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 8; spacing: 10
                Repeater { model: [["Paper", 360], ["Measure", 140], ["Estimate", 90], ["Interval", 130], ["Level vs reference", 220]]
                    delegate: Text { Layout.preferredWidth: modelData[1]; Layout.fillWidth: modelData[1] > 200; text: modelData[0]; font.pixelSize: 12; color: root.t3 } } }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line2; Layout.topMargin: 6 }
            Repeater { model: pp.d ? pp.d.rows : []
                delegate: Rectangle { Layout.fillWidth: true; implicitHeight: er2.implicitHeight + 14; color: "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                    RowLayout { id: er2; y: 7; width: parent.width; spacing: 10
                        ColumnLayout { Layout.preferredWidth: 360; Layout.fillWidth: true; spacing: 1
                            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.title; font.pixelSize: 13; color: root.primary; font.underline: tm.containsMouse
                                   MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.openPaper(modelData.si) } }
                            Text { Layout.fillWidth: true; elide: Text.ElideRight; text: modelData.design + " · " + modelData.id; font.pixelSize: 11; color: root.t3 } }
                        Cell { w: 140; text: modelData.measure }
                        Item { Layout.preferredWidth: 90; implicitHeight: 18; ValueMark { v: modelData.value } }
                        Text { Layout.preferredWidth: 130; text: modelData.ci; font.family: root.mono; font.pixelSize: 12; color: modelData.ci === "none" ? root.t4 : root.ink }
                        Cell { w: 220; text: modelData.level; color: root.t2; font.pixelSize: 13 } } } }
        }
    }

    Component {
        id: paperPage
        ColumnLayout {
            id: pg
            spacing: 0
            property var d: PR.paperDetail(root.route.si)
            Crumbs { items: [["Home", {v: "home"}], ["Paper", null], [pg.d.id, null]] }
            RowLayout { Layout.fillWidth: true; Layout.topMargin: 6
                ColumnLayout { Layout.fillWidth: true; spacing: 3
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: pg.d.title; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
                    Text { text: pg.d.id; font.family: root.mono; font.pixelSize: 13; color: root.t3 } }
                Btn { visible: !!pg.d.link; text: "Open at " + pg.d.linkName; onClicked: Qt.openUrlExternally(pg.d.link) } }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 12; height: 1; color: root.line }
            GridLayout { columns: 2; columnSpacing: 20; rowSpacing: 4; Layout.fillWidth: true; Layout.topMargin: 12
                Text { text: "Design"; color: root.t3; font.pixelSize: 14 } Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: pg.d.design; font.pixelSize: 14; color: root.ink }
                Text { text: "Population"; color: root.t3; font.pixelSize: 14 } Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: pg.d.population; font.pixelSize: 14; color: root.ink }
                Text { text: "Estimates"; color: root.t3; font.pixelSize: 14 } Text { text: PR.fmt(pg.d.nEst); font.family: root.mono; font.pixelSize: 14; color: root.ink } }
            H2 { text: "Author conclusions"; sub: String(pg.d.claims.length) }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line; Layout.topMargin: 6 }
            Repeater { model: pg.d.claims; delegate: ClaimRow { c: modelData; showPaper: false } }
            H2 { visible: !root.raw; text: "Bias flags"; sub: String(pg.d.flags.length) }
            Repeater { model: root.raw ? [] : pg.d.flags
                delegate: RowLayout { Layout.fillWidth: true; Layout.topMargin: 6; spacing: 10
                    Cell { w: 180; text: modelData.type } Cell { w: 80; text: modelData.sev; color: root.t2 } Cell { w: 600; text: modelData.note } } }
            H2 { text: "Estimates"; sub: String(pg.d.nEst) }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.line2; Layout.topMargin: 6 }
            Repeater { model: pg.d.est
                delegate: Rectangle { Layout.fillWidth: true; implicitHeight: pr2.implicitHeight + 12; color: pm2.containsMouse ? root.hover : "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: root.line }
                    RowLayout { id: pr2; y: 6; width: parent.width; spacing: 10
                        Cell { w: 380; text: modelData.pair; color: root.primary } Cell { w: 140; text: modelData.measure }
                        Item { Layout.preferredWidth: 90; implicitHeight: 18; ValueMark { v: modelData.value } }
                        Text { Layout.preferredWidth: 130; text: modelData.ci; font.family: root.mono; font.pixelSize: 12 }
                        Cell { w: 220; text: modelData.level; color: root.t2; font.pixelSize: 13 } }
                    MouseArea { id: pm2; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go({v: "pair", x: modelData.x, y: modelData.y}) } } }
        }
    }

    Component {
        id: networkPage
        ColumnLayout {
            id: np
            spacing: 0
            property string filter: ""
            property int minShared: 1
            property var g: PR.networkGraph(filter, minShared)
            Crumbs { items: [["Home", {v: "home"}], ["Paper network", null]] }
            Text { Layout.topMargin: 6; text: "Paper network"; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Papers linked when they report on the same exposure and outcome. Line weight counts shared pairs. Click a paper to read its claims."; font.pixelSize: 14; color: root.t3 }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 12; height: 1; color: root.line }
            RowLayout { Layout.topMargin: 12; spacing: 12
                Rectangle { implicitWidth: 380; implicitHeight: 32; radius: 6; border.color: nf.activeFocus ? root.primary : root.line2
                    TextField { id: nf; anchors.fill: parent; background: null; font.pixelSize: 14; placeholderText: "Filter by title or concept: coffee, water, rumination"; onTextChanged: ft.restart() }
                    Timer { id: ft; interval: 300; onTriggered: np.filter = nf.text } }
                Text { text: "Shared pairs at least"; font.pixelSize: 13; color: root.t3 }
                Row { spacing: 4
                    Repeater { model: [1, 2, 3, 5]
                        delegate: Rectangle { width: 28; height: 26; radius: 5; color: np.minShared === modelData ? root.primary : root.bg; border.color: root.line2
                            Text { anchors.centerIn: parent; text: modelData; font.pixelSize: 13; color: np.minShared === modelData ? "#ffffff" : root.t2 }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: np.minShared = modelData } } } }
                Text { text: np.g.note; font.family: root.mono; font.pixelSize: 12; color: root.t3 } }
            Legend { Layout.topMargin: 10; items: PR.DESIGN.map(function (d) { return [d[2], d[0]] }) }
            GraphView { Layout.topMargin: 8; implicitHeight: Math.max(560, pageFlick.height - 210); gx: 0.03; gy: 0.03; g: np.g.nodes.length ? np.g : null
                onNodeClicked: (n) => root.openPaper(n.si) }
        }
    }

    Component {
        id: aboutPage
        ColumnLayout {
            spacing: 6
            Crumbs { items: [["Home", {v: "home"}], ["About", null]] }
            Text { text: "About Pramana"; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
            Text { text: "Protocol and app, data and lenses."; font.pixelSize: 14; color: root.t3 }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 6; height: 1; color: root.line }
            Repeater {
                model: [["Protocol and app", "The Pramana protocol is an open format for evidence. Each paper is reduced to the estimates it reports, each published claim to the fields it asserts, and every record points back to the sentence or table it came from. This Basecamp module is one reader of that format; the web app at adb3502.github.io/pramana-protocol is another. Anyone can build more."],
                        ["Data and lenses", "The data layer records what a source reported and what a claim says, with no judgment attached. A lens is a named, versioned set of rules that reads the data and labels the differences. This app ships Pramana fidelity lens v1 by adb. Switch the toolbar to Raw data to see the records with every lens label removed."],
                        ["Claude in this app", "Search runs on Claude Sonnet through the Pramana relay, so no key lives in this module. Claude maps a question to the concepts that exist in the database and to keywords, the app retrieves the matching records locally, and Claude then describes only those records, citing paper IDs. Claude applies no lens and gives no verdict."],
                        ["How the graph is built", "Two model readers extract every estimate from each paper. Where they disagree, a judge decides. Concepts are linked to Wikidata so that the same exposure or outcome joins up across papers. Where only an abstract is open, the record says so."],
                        ["Logos", "The snapshot is published to Logos Storage under the content ID below and mirrored into the receipts core module, a C++ Logos module holding it in SQLite. This UI module is the QML front end that Basecamp loads beside it."]]
                delegate: ColumnLayout { Layout.fillWidth: true; Layout.maximumWidth: 820; spacing: 4
                    H2 { text: modelData[0] }
                    Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData[1]; font.pixelSize: 14; lineHeight: 1.15; color: root.ink } }
            }
            H2 { text: "Snapshot" }
            GridLayout { columns: 2; columnSpacing: 20; rowSpacing: 4
                Repeater { model: [["Logos Storage CID", PR.CID], ["Corpus", root.cnt.corpus], ["Papers", PR.fmt(root.cnt.papers)], ["Independent sources", PR.fmt(root.cnt.sources)], ["Extracted estimates", PR.fmt(root.cnt.estimates)], ["Exposure and outcome pairs", PR.fmt(root.cnt.pairs)], ["Core module", root.coreNote]]
                    delegate: Repeater { property var row: modelData; model: 2
                        delegate: Text { text: row[index]; Layout.maximumWidth: index ? 700 : 200; wrapMode: Text.Wrap; font.pixelSize: 14; color: index ? root.ink : root.t3; font.family: index && row[0] === "Logos Storage CID" ? root.mono : "" } } } }
            H2 { text: "Links" }
            Row { spacing: 8
                Btn { text: "Web app"; onClicked: Qt.openUrlExternally("https://adb3502.github.io/pramana-protocol/") }
                Btn { text: "Contribute papers"; onClicked: Qt.openUrlExternally("https://adb3502.github.io/pramana-protocol/contribute/") }
                Btn { text: "Source code"; onClicked: Qt.openUrlExternally("https://github.com/adb3502/pramana") } }
        }
    }
}
