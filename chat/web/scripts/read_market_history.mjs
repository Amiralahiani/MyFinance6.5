const [mnemonic, yearText] = process.argv.slice(2).map((value) => value?.trim());
if (!/^[A-Z0-9]{1,12}$/.test((mnemonic ?? "").toUpperCase()) || !/^20\d{2}$/.test(yearText ?? "")) {
  throw new Error("A mnemonic and a four-digit year are required.");
}

const year = Number(yearText);
const sourceUrl = "https://tunis-stockexchange.com/sites/default/files/historique/data_json/market_resume.ndjson";
const response = await fetch(sourceUrl, { headers: { Accept: "application/x-ndjson, application/json" } });
if (!response.ok || !response.body) throw new Error("The official historical dataset is unavailable.");

const decoder = new TextDecoder();
const reader = response.body.getReader();
let buffer = "";
const points = [];
let latestDate = "";
const target = mnemonic.toUpperCase();

function takeLine(line) {
  if (!line.trim()) return;
  const bucket = JSON.parse(line);
  if (String(bucket.annee) !== String(year) || !Array.isArray(bucket.data)) return;
  for (const row of bucket.data) {
    if (row?.mnemo !== target || row?.ligne !== "Ligne Mère" || typeof row.dateSeance !== "string") continue;
    if (typeof row.cloture !== "number" || !Number.isFinite(row.cloture)) continue;
    points.push({
      date: row.dateSeance,
      close: row.cloture,
      reference: typeof row.coursReference === "number" ? row.coursReference : null,
      change_percent: typeof row.varJour === "number" ? row.varJour : null,
      volume: typeof row.quantites === "number" ? row.quantites : null,
      turnover_tnd: typeof row.capitaux === "number" ? row.capitaux : null,
      transactions: typeof row.echanges === "number" ? row.echanges : null,
      market_capitalization_md: typeof row.capitalisationBoursiereMD === "number" ? row.capitalisationBoursiereMD : null,
      dividend_yield_percent: typeof row.dividendYield === "number" ? row.dividendYield : null,
    });
    latestDate = row.dateSeance > latestDate ? row.dateSeance : latestDate;
  }
}

try {
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) takeLine(line);
    if (done) break;
  }
  takeLine(buffer);
} finally {
  reader.releaseLock();
}

points.sort((left, right) => left.date.localeCompare(right.date));
if (points.length < 2) throw new Error(`No usable official history is available for ${target} in ${year}.`);
process.stdout.write(JSON.stringify({
  mnemonic: target,
  year,
  points,
  source_url: sourceUrl,
  retrieved_at: new Date().toISOString(),
  last_observation_date: latestDate,
}));
