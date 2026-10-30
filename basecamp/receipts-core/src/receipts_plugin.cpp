#include "receipts_plugin.h"
#include "logos_api.h"

#include <QCryptographicHash>
#include <QDebug>
#include <QDir>
#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSet>
#include <QSqlDatabase>
#include <QSqlError>
#include <QSqlQuery>
#include <QStandardPaths>
#include <QUrl>
#include <QVariant>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <algorithm>
#include <cmath>

// Named connection so this module's SQLite handle never clashes with another module's.
static constexpr char CONNECTION[] = "logos-claim-receipts";

static QString compact(const QJsonDocument& d) { return QString::fromUtf8(d.toJson(QJsonDocument::Compact)); }
static QString compact(const QJsonArray& a) { return compact(QJsonDocument(a)); }
static QString compact(const QJsonObject& o) { return compact(QJsonDocument(o)); }

ReceiptsPlugin::ReceiptsPlugin(QObject* parent) : QObject(parent) { qDebug() << "ReceiptsPlugin: ready"; }

ReceiptsPlugin::~ReceiptsPlugin()
{
    if (QSqlDatabase::contains(CONNECTION)) {
        {
            QSqlDatabase db = QSqlDatabase::database(CONNECTION);
            if (db.isOpen()) db.close();
        }
        QSqlDatabase::removeDatabase(CONNECTION);
    }
}

void ReceiptsPlugin::initLogos(LogosAPI* api)
{
    logosAPI = api;
    if (!openDatabase()) qWarning() << "ReceiptsPlugin: database init failed";
}

bool ReceiptsPlugin::openDatabase()
{
    const QString dataDir = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    QDir().mkpath(dataDir);
    QSqlDatabase db = QSqlDatabase::addDatabase("QSQLITE", CONNECTION);
    db.setDatabaseName(dataDir + "/claim_receipts.db");
    if (!db.open()) { qWarning() << "ReceiptsPlugin: cannot open db" << db.lastError(); return false; }
    QSqlQuery q(db);
    const char* ddl[] = {
        "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
        "CREATE TABLE IF NOT EXISTS concepts (i INTEGER PRIMARY KEY, label TEXT, n INTEGER, words TEXT)",
        "CREATE TABLE IF NOT EXISTS pairs (x INTEGER, y INTEGER, est INTEGER, studies INTEGER, sources INTEGER, lower INTEGER, nul INTEGER, higher INTEGER, noci INTEGER)",
        "CREATE TABLE IF NOT EXISTS studies (i INTEGER PRIMARY KEY, doc TEXT, title TEXT, design TEXT, source TEXT)",
        "CREATE TABLE IF NOT EXISTS claims (study INTEGER, kind TEXT, section TEXT, text TEXT)",
        "CREATE TABLE IF NOT EXISTS estimates (study INTEGER, x INTEGER, y INTEGER, measure TEXT, value REAL, lo REAL, hi REAL, level TEXT, ref TEXT)",
        "CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, quote TEXT, json TEXT)",
        "CREATE INDEX IF NOT EXISTS est_xy ON estimates (x, y)"
    };
    for (const char* s : ddl) if (!q.exec(s)) { qWarning() << "ReceiptsPlugin: ddl failed" << q.lastError(); return false; }
    return true;
}

// Same normalisation as the web app: lower case, words of 3+ letters, stop words dropped, light stemming.
QStringList ReceiptsPlugin::tokens(const QString& text)
{
    static const QSet<QString> stop = QSet<QString>({"the","and","for","with","are","was","were","been","its","this","that","than","from","into","your","you","our","their",
        "his","her","them","they","can","could","may","might","will","would","should","does","did","not","but","also","more","most","less","very","ultimate","just",
        "being","has","have","had","about","over","per","day","study","studies","new","says","said","found","finds","shows","researchers","according"});
    static const QRegularExpression words("[a-z0-9]+");
    QStringList out;
    auto it = words.globalMatch(text.toLower());
    while (it.hasNext()) {
        QString w = it.next().captured(0);
        if (w.size() <= 2 || stop.contains(w)) continue;
        if (w.endsWith("ies")) w = w.left(w.size() - 3) + "y";
        else if (w.endsWith("ing")) w.chop(3);
        else if (w.endsWith("ed")) w.chop(2);
        else if (w.endsWith("es")) w.chop(2);
        else if (w.endsWith("s")) w.chop(1);
        out << w;
    }
    return out;
}

// Everyday words to the vocabulary the graph uses.
QString ReceiptsPlugin::expand(const QString& text)
{
    QString s = " " + text.toLower() + " ";
    const QList<QPair<QString, QString>> rules = {
        {"negative thinking|overthinking|worry|worrying|brooding", " rumination cognitive "},
        {"\\bbrain\\b|memory", " cognition cognitive dysfunction "},
        {"heart disease|heart attack|cardiac", " heart diseases cardiovascular diseases coronary disease "},
        {"\\bdeath\\b|longevity|lifespan", " mortality "},
        {"blood sugar|glucose", " blood glucose "},
        {"\\bai\\b|chatgpt|data cent(er|re)s?", " data center water "}};
    for (const auto& r : rules) {
        QRegularExpression re(r.first);
        if (re.match(s).hasMatch()) s += r.second;
    }
    return s;
}

QString ReceiptsPlugin::loadSnapshot(const QString& path)
{
    QFile f(QUrl(path).isLocalFile() ? QUrl(path).toLocalFile() : path);
    if (!f.open(QIODevice::ReadOnly)) return compact(QJsonObject{{"ok", false}, {"error", "cannot open " + path}});
    const QByteArray raw = f.readAll();
    const QString sha = QString::fromLatin1(QCryptographicHash::hash(raw, QCryptographicHash::Sha256).toHex());
    QJsonParseError pe;
    const QJsonObject d = QJsonDocument::fromJson(raw, &pe).object();
    if (pe.error != QJsonParseError::NoError) return compact(QJsonObject{{"ok", false}, {"error", pe.errorString()}});

    QSqlDatabase db = QSqlDatabase::database(CONNECTION);
    db.transaction();
    QSqlQuery q(db);
    for (const char* t : {"concepts", "pairs", "studies", "claims", "estimates", "receipts"}) q.exec(QString("DELETE FROM %1").arg(t));

    q.prepare("INSERT INTO concepts VALUES (?,?,?,?)");
    const QJsonArray K = d["K"].toArray();
    for (int i = 0; i < K.size(); ++i) {
        const QJsonArray k = K[i].toArray();
        QStringList w = tokens(k[0].toString());
        for (const auto& t : k[2].toArray()) w << tokens(t.toString());
        w.removeDuplicates();
        q.addBindValue(i); q.addBindValue(k[0].toString()); q.addBindValue(k[1].toInt()); q.addBindValue(w.join(' '));
        q.exec();
    }
    q.prepare("INSERT INTO pairs VALUES (?,?,?,?,?,?,?,?,?)");
    for (const auto& pv : d["P"].toArray()) {
        const QJsonArray p = pv.toArray();
        for (int j = 0; j < 9; ++j) q.addBindValue(p[j].toInt());
        q.exec();
    }
    QSqlQuery qc(db);
    q.prepare("INSERT INTO studies VALUES (?,?,?,?,?)");
    qc.prepare("INSERT INTO claims VALUES (?,?,?,?)");
    const QJsonArray S = d["S"].toArray();
    for (int i = 0; i < S.size(); ++i) {
        const QJsonArray s = S[i].toArray();
        q.addBindValue(i); q.addBindValue(s[0].toString()); q.addBindValue(s[1].toString()); q.addBindValue(s[2].toString()); q.addBindValue(s[3].toString());
        q.exec();
        for (const auto& cv : s[4].toArray()) {
            const QJsonArray c = cv.toArray();
            qc.addBindValue(i); qc.addBindValue(c[0].toString()); qc.addBindValue(c[1].toString()); qc.addBindValue(c[2].toString());
            qc.exec();
        }
    }
    q.prepare("INSERT INTO estimates VALUES (?,?,?,?,?,?,?,?,?)");
    for (const auto& rv : d["R"].toArray()) {
        const QJsonArray r = rv.toArray();
        q.addBindValue(r[0].toInt()); q.addBindValue(r[1].toInt()); q.addBindValue(r[2].toInt()); q.addBindValue(r[3].toString());
        q.addBindValue(r[4].toDouble());
        q.addBindValue(r[5].isNull() ? QVariant() : QVariant(r[5].toDouble()));
        q.addBindValue(r[6].isNull() ? QVariant() : QVariant(r[6].toDouble()));
        q.addBindValue(r[7].toString()); q.addBindValue(r[8].toString());
        q.exec();
    }
    q.prepare("INSERT INTO receipts VALUES (?,?,?)");
    for (const auto& rv : d["receipts"].toArray()) {
        const QJsonObject r = rv.toObject();
        q.addBindValue(r["id"].toString()); q.addBindValue(r["quote"].toString()); q.addBindValue(compact(r));
        q.exec();
    }
    q.prepare("INSERT OR REPLACE INTO meta VALUES (?,?)");
    const QList<QPair<QString, QString>> meta = {{"corpus", d["corpus"].toString()}, {"counts", compact(d["counts"].toObject())}, {"sha256", sha}, {"loaded_from", path}};
    for (const auto& m : meta) { q.addBindValue(m.first); q.addBindValue(m.second); q.exec(); }
    db.commit();
    emit eventResponse("snapshotLoaded", QVariantList{sha});
    return stats();
}

QString ReceiptsPlugin::stats()
{
    QJsonObject o;
    QSqlQuery q(QSqlDatabase::database(CONNECTION));
    if (q.exec("SELECT k, v FROM meta")) while (q.next()) o[q.value(0).toString()] = q.value(1).toString();
    for (const char* t : {"concepts", "pairs", "studies", "claims", "estimates", "receipts"})
        if (q.exec(QString("SELECT COUNT(*) FROM %1").arg(t)) && q.next()) o[t] = q.value(0).toInt();
    return compact(o);
}

bool ReceiptsPlugin::setSnapshotCid(const QString& cid)
{
    QSqlQuery q(QSqlDatabase::database(CONNECTION));
    q.prepare("INSERT OR REPLACE INTO meta VALUES ('cid', ?)");
    q.addBindValue(cid);
    return q.exec();
}

QString ReceiptsPlugin::searchPairs(const QString& query)
{
    const QStringList qtl = tokens(expand(query));
    const QSet<QString> qt(qtl.begin(), qtl.end());
    QSqlDatabase db = QSqlDatabase::database(CONNECTION);
    QHash<int, double> score;
    QHash<int, QString> label;
    QSqlQuery q(db);
    if (q.exec("SELECT i, label, n, words FROM concepts")) while (q.next()) {
        const QStringList lw = tokens(q.value(1).toString());
        if (lw.isEmpty()) continue;
        bool full = std::all_of(lw.begin(), lw.end(), [&](const QString& w) { return qt.contains(w); });
        int hit = 0;
        for (const auto& w : q.value(3).toString().split(' ', Qt::SkipEmptyParts)) if (qt.contains(w)) ++hit;
        if (full || hit >= 2) {
            score[q.value(0).toInt()] = (full ? 2.0 : 0.0) + double(hit) / lw.size() + std::log10(1.0 + q.value(2).toInt()) * 0.15;
            label[q.value(0).toInt()] = q.value(1).toString();
        }
    }
    struct Hit { QJsonObject o; double s; bool both; int studies; };
    QList<Hit> hits;
    if (q.exec("SELECT x, y, est, studies, sources, lower, nul, higher, noci FROM pairs")) while (q.next()) {
        const int x = q.value(0).toInt(), y = q.value(1).toInt();
        if (!score.contains(x) && !score.contains(y)) continue;
        QJsonObject o{{"x", x}, {"y", y}, {"est", q.value(2).toInt()}, {"studies", q.value(3).toInt()}, {"sources", q.value(4).toInt()},
                      {"lower", q.value(5).toInt()}, {"nul", q.value(6).toInt()}, {"higher", q.value(7).toInt()}, {"noci", q.value(8).toInt()}};
        hits << Hit{o, score.value(x) + score.value(y), score.contains(x) && score.contains(y), q.value(3).toInt()};
    }
    const bool anyBoth = std::any_of(hits.begin(), hits.end(), [](const Hit& h) { return h.both; });
    if (anyBoth) hits.erase(std::remove_if(hits.begin(), hits.end(), [](const Hit& h) { return !h.both; }), hits.end());
    std::sort(hits.begin(), hits.end(), [](const Hit& a, const Hit& b) { return a.s != b.s ? a.s > b.s : a.studies > b.studies; });
    QJsonArray out;
    QSqlQuery ql(db);
    for (int i = 0; i < std::min<int>(6, hits.size()); ++i) {
        QJsonObject o = hits[i].o;
        for (const char* side : {"x", "y"}) {
            ql.prepare("SELECT label FROM concepts WHERE i = ?"); ql.addBindValue(o[side].toInt());
            if (ql.exec() && ql.next()) o[QString(side) + "_label"] = ql.value(0).toString();
        }
        out.append(o);
    }
    return compact(out);
}

QString ReceiptsPlugin::pairEstimates(const QString& x, const QString& y)
{
    QSqlQuery q(QSqlDatabase::database(CONNECTION));
    q.prepare("SELECT s.doc, s.title, e.measure, e.value, e.lo, e.hi, e.level, e.ref FROM estimates e JOIN studies s ON s.i = e.study "
              "WHERE e.x = ? AND e.y = ? ORDER BY (e.lo IS NULL), s.doc LIMIT 40");
    q.addBindValue(x.toInt()); q.addBindValue(y.toInt());
    QJsonArray out;
    if (q.exec()) while (q.next()) out.append(QJsonObject{{"doc", q.value(0).toString()}, {"title", q.value(1).toString()}, {"measure", q.value(2).toString()},
        {"value", q.value(3).toDouble()}, {"lo", q.value(4).isNull() ? QJsonValue() : QJsonValue(q.value(4).toDouble())},
        {"hi", q.value(5).isNull() ? QJsonValue() : QJsonValue(q.value(5).toDouble())}, {"level", q.value(6).toString()}, {"ref", q.value(7).toString()}});
    return compact(out);
}

QString ReceiptsPlugin::searchClaims(const QString& query)
{
    const QStringList qt = tokens(query);
    QJsonArray out;
    if (qt.isEmpty()) return compact(out);
    struct Hit { QJsonObject o; int h; };
    QList<Hit> hits;
    QSqlQuery q(QSqlDatabase::database(CONNECTION));
    if (q.exec("SELECT c.kind, c.section, c.text, s.title, s.design, s.doc FROM claims c JOIN studies s ON s.i = c.study")) while (q.next()) {
        const QStringList ctl = tokens(q.value(2).toString());
        const QSet<QString> ct(ctl.begin(), ctl.end());
        int h = 0;
        for (const auto& w : qt) if (ct.contains(w)) ++h;
        if (h >= std::min<int>(2, qt.size()))
            hits << Hit{QJsonObject{{"kind", q.value(0).toString()}, {"section", q.value(1).toString()}, {"text", q.value(2).toString()},
                                    {"title", q.value(3).toString()}, {"design", q.value(4).toString()}, {"doc", q.value(5).toString()}}, h};
    }
    std::stable_sort(hits.begin(), hits.end(), [](const Hit& a, const Hit& b) { return a.h > b.h; });
    for (int i = 0; i < std::min<int>(8, hits.size()); ++i) out.append(hits[i].o);
    return compact(out);
}

QString ReceiptsPlugin::listReceipts()
{
    QJsonArray out;
    QSqlQuery q(QSqlDatabase::database(CONNECTION));
    if (q.exec("SELECT json FROM receipts")) while (q.next()) out.append(QJsonDocument::fromJson(q.value(0).toString().toUtf8()).object());
    return compact(out);
}

QString ReceiptsPlugin::matchReceipt(const QString& query)
{
    const QStringList qtl = tokens(query);
    const QSet<QString> qt(qtl.begin(), qtl.end());
    double best = 0.35; QString json = "{}";
    QSqlQuery q(QSqlDatabase::database(CONNECTION));
    if (q.exec("SELECT quote, json FROM receipts")) while (q.next()) {
        const QStringList rt = tokens(q.value(0).toString());
        int h = 0;
        for (const auto& w : rt) if (qt.contains(w)) ++h;
        const double s = double(h) / std::max(4, std::min<int>(rt.size(), 10));
        if (s >= best) { best = s; json = q.value(1).toString(); }
    }
    return json;
}

// ── Claude via the Pramana relay ────────────────────────────────────────
// Fallback relay; the live address is read from relay.json on the Pramana site so a tunnel restart needs no rebuild.
static const char* RELAY_URL = "https://identify-sensors-screensaver-homeless.trycloudflare.com";
static const char* RELAY_INDEX = "https://adb3502.github.io/pramana-protocol/relay.json";

QString ReceiptsPlugin::askStart(const QString& prompt, const QString& maxTokens)
{
    if (!m_net) m_net = new QNetworkAccessManager(this);
    const QString id = QString::number(++m_jobSeq);
    m_jobs.insert(id, AskJob{});
    QJsonObject msg{{"role", "user"}, {"content", prompt}};
    QJsonObject body{{"model", "claude-sonnet-4-5"}, {"max_tokens", qBound(64, maxTokens.toInt() > 0 ? maxTokens.toInt() : 1200, 1500)},
                     {"stream", true}, {"messages", QJsonArray{msg}}};
    const QByteArray payload = QJsonDocument(body).toJson(QJsonDocument::Compact);
    QString env = qEnvironmentVariable("PRAMANA_RELAY");
    if (!env.isEmpty()) { postAsk(id, env, payload); return id; }
    QNetworkRequest ireq{QUrl(QString::fromLatin1(RELAY_INDEX))};
    ireq.setAttribute(QNetworkRequest::CacheLoadControlAttribute, QNetworkRequest::AlwaysNetwork);
    ireq.setTransferTimeout(6000);
    QNetworkReply* ir = m_net->get(ireq);
    connect(ir, &QNetworkReply::finished, this, [this, ir, id, payload]() {
        QString base = QJsonDocument::fromJson(ir->readAll()).object().value("relay").toString();
        if (!base.startsWith("https://")) base = QString::fromLatin1(RELAY_URL);
        ir->deleteLater();
        postAsk(id, base + "/ai", payload);
    });
    return id;
}

void ReceiptsPlugin::postAsk(const QString& id, const QString& url, const QByteArray& payload)
{
    QNetworkRequest req{QUrl(url)};
    req.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    QNetworkReply* reply = m_net->post(req, payload);
    auto drain = [this, id](const QByteArray& chunk) {
        auto it = m_jobs.find(id); if (it == m_jobs.end()) return;
        it->buf += chunk;
        int nl;
        while ((nl = it->buf.indexOf('\n')) >= 0) {
            const QByteArray line = it->buf.left(nl).trimmed(); it->buf.remove(0, nl + 1);
            if (!line.startsWith("data:")) continue;
            const QJsonObject ev = QJsonDocument::fromJson(line.mid(5).trimmed()).object();
            if (ev.value("type").toString() == "content_block_delta") it->text += ev.value("delta").toObject().value("text").toString();
        }
    };
    connect(reply, &QNetworkReply::readyRead, this, [reply, drain]() {
        if (reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() == 200) drain(reply->readAll());
    });
    connect(reply, &QNetworkReply::finished, this, [this, reply, id, drain]() {
        auto it = m_jobs.find(id);
        if (it != m_jobs.end()) {
            const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            const QByteArray rest = reply->readAll();
            if (status == 200) { drain(rest + "\n"); }
            else {
                QString m = QJsonDocument::fromJson(rest).object().value("error").toObject().value("message").toString();
                if (m.isEmpty()) m = status ? QString("HTTP %1").arg(status) : reply->errorString();
                it = m_jobs.find(id); if (it != m_jobs.end()) it->error = "Shared Claude: " + m;
            }
            it = m_jobs.find(id); if (it != m_jobs.end()) it->done = true;
        }
        reply->deleteLater();
    });
}

QString ReceiptsPlugin::askPoll(const QString& id)
{
    auto it = m_jobs.find(id);
    if (it == m_jobs.end()) return compact(QJsonObject{{"done", true}, {"error", "unknown job"}, {"text", ""}});
    const QJsonObject o{{"text", it->text}, {"done", it->done}, {"error", it->error}};
    if (it->done) m_jobs.erase(it);
    return compact(o);
}
