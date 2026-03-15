const NATIONAL_KEY = "__NATIONAL__";

const COLORS = {
  labor: "#eb6a34",
  capital: "#268c85",
  tfp: "#2a4b6a",
  output: "#0f1d2f"
};

const state = {
  mode: "yoy",
  country: null,
  industry: null
};

const store = {
  yoy: [],
  cumulative: [],
  qa: null,
  countries: [],
  industriesByCountry: new Map(),
  seriesByMode: {
    yoy: new Map(),
    cumulative: new Map()
  }
};

function parseNum(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function normalizeIndustry(code, name) {
  if (code && name) {
    return { code, name };
  }
  return { code: NATIONAL_KEY, name: "National total" };
}

function normalizeYoY(row) {
  const industry = normalizeIndustry(row.industry_code, row.industry_name);
  return {
    country_code: row.country_code,
    country_name: row.country_name,
    industry_code: industry.code,
    industry_name: industry.name,
    series_type: row.series_type,
    year: parseNum(row.year),
    g_y: parseNum(row.g_y),
    contrib_k: parseNum(row.contrib_k),
    contrib_l: parseNum(row.contrib_l),
    contrib_tfp: parseNum(row.contrib_tfp),
    residual: parseNum(row.residual),
    method_version: row.method_version
  };
}

function normalizeCumulative(row) {
  const industry = normalizeIndustry(row.industry_code, row.industry_name);
  return {
    country_code: row.country_code,
    country_name: row.country_name,
    industry_code: industry.code,
    industry_name: industry.name,
    series_type: row.series_type,
    base_year: parseNum(row.base_year),
    year: parseNum(row.year),
    g_y: parseNum(row.cum_g_y),
    contrib_k: parseNum(row.cum_contrib_k),
    contrib_l: parseNum(row.cum_contrib_l),
    contrib_tfp: parseNum(row.cum_contrib_tfp),
    residual: parseNum(row.cum_residual),
    method_version: row.method_version
  };
}

function keyFor(countryCode, industryCode) {
  return `${countryCode}::${industryCode}`;
}

function buildIndexes() {
  const countriesByCode = new Map();
  const industriesByCountry = new Map();

  for (const mode of ["yoy", "cumulative"]) {
    const seriesMap = new Map();
    for (const row of store[mode]) {
      countriesByCode.set(row.country_code, row.country_name);

      if (!industriesByCountry.has(row.country_code)) {
        industriesByCountry.set(row.country_code, new Map());
      }
      industriesByCountry.get(row.country_code).set(row.industry_code, row.industry_name);

      const key = keyFor(row.country_code, row.industry_code);
      if (!seriesMap.has(key)) {
        seriesMap.set(key, []);
      }
      seriesMap.get(key).push(row);
    }

    for (const series of seriesMap.values()) {
      series.sort((a, b) => a.year - b.year);
    }
    store.seriesByMode[mode] = seriesMap;
  }

  store.countries = [...countriesByCode.entries()]
    .map(([code, name]) => ({ code, name }))
    .sort((a, b) => a.name.localeCompare(b.name));

  store.industriesByCountry = new Map(
    [...industriesByCountry.entries()].map(([country, industryMap]) => {
      const industries = [...industryMap.entries()].map(([code, name]) => ({ code, name }));
      industries.sort((a, b) => {
        if (a.code === NATIONAL_KEY) return -1;
        if (b.code === NATIONAL_KEY) return 1;
        return a.name.localeCompare(b.name);
      });
      return [country, industries];
    })
  );
}

function initControls() {
  const countrySelect = document.getElementById("countrySelect");
  const industrySelect = document.getElementById("industrySelect");
  const modeInputs = [...document.querySelectorAll('input[name="mode"]')];

  countrySelect.innerHTML = "";
  for (const country of store.countries) {
    const option = document.createElement("option");
    option.value = country.code;
    option.textContent = country.name;
    countrySelect.appendChild(option);
  }

  state.country = store.countries[0]?.code || null;
  countrySelect.value = state.country;

  const desiredIndustry = NATIONAL_KEY;
  repopulateIndustries(desiredIndustry);

  countrySelect.addEventListener("change", () => {
    state.country = countrySelect.value;
    repopulateIndustries(NATIONAL_KEY);
    render();
  });

  industrySelect.addEventListener("change", () => {
    state.industry = industrySelect.value;
    render();
  });

  for (const input of modeInputs) {
    input.addEventListener("change", () => {
      state.mode = input.value;
      render();
    });
  }
}

function repopulateIndustries(preferredCode) {
  const industrySelect = document.getElementById("industrySelect");
  const options = store.industriesByCountry.get(state.country) || [];
  industrySelect.innerHTML = "";

  for (const industry of options) {
    const option = document.createElement("option");
    option.value = industry.code;
    option.textContent = industry.name;
    industrySelect.appendChild(option);
  }

  const exists = options.some((i) => i.code === preferredCode);
  state.industry = exists ? preferredCode : options[0]?.code || null;
  industrySelect.value = state.industry;
}

function getSeries() {
  if (!state.country || !state.industry) {
    return [];
  }
  const key = keyFor(state.country, state.industry);
  return store.seriesByMode[state.mode].get(key) || [];
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "n/a";
  }
  return value.toFixed(digits);
}

function renderMetrics(series) {
  const root = document.getElementById("metricGrid");
  root.innerHTML = "";

  const latest = series.at(-1);
  const cards = [
    {
      label: "Latest Year",
      value: latest ? String(latest.year) : "n/a"
    },
    {
      label: state.mode === "yoy" ? "Output Growth (YoY)" : "Output Growth (Cumulative)",
      value: latest ? `${fmt(latest.g_y)} pp` : "n/a"
    },
    {
      label: "Capital Contribution",
      value: latest ? `${fmt(latest.contrib_k)} pp` : "n/a"
    },
    {
      label: "Labor Contribution",
      value: latest ? `${fmt(latest.contrib_l)} pp` : "n/a"
    },
    {
      label: "TFP Contribution",
      value: latest ? `${fmt(latest.contrib_tfp)} pp` : "n/a"
    },
    {
      label: "Identity Residual",
      value: latest ? fmt(latest.residual, 6) : "n/a"
    }
  ];

  for (const card of cards) {
    const div = document.createElement("article");
    div.className = "metric";
    div.innerHTML = `<p class="label">${card.label}</p><p class="value">${card.value}</p>`;
    root.appendChild(div);
  }
}

function renderReview() {
  const reviewRoot = document.getElementById("reviewGrid");
  const qa = store.qa;
  if (!qa) {
    reviewRoot.innerHTML = "";
    return;
  }

  const items = [
    {
      title: "Method",
      main: qa.method_version,
      extra: `Created: ${qa.created_at_utc}`
    },
    {
      title: "Coverage",
      main: `${qa.coverage.countries_in_yoy} countries, ${qa.coverage.industries_in_yoy} industries`,
      extra: `Years: ${qa.coverage.years_min} to ${qa.coverage.years_max}`
    },
    {
      title: "Rows",
      main: `YoY: ${qa.rows.yoy_total.toLocaleString()}`,
      extra: `Cumulative: ${qa.rows.cumulative_total.toLocaleString()}`
    },
    {
      title: "Country Macro Rows",
      main: qa.rows.yoy_country_macro.toLocaleString(),
      extra: "series_type = country_macro"
    },
    {
      title: "Country Industry Rows",
      main: qa.rows.yoy_country_industry.toLocaleString(),
      extra: "series_type = country_industry"
    },
    {
      title: "Max Residual (abs)",
      main: Number(qa.identity_checks.yoy_max_abs_residual).toExponential(2),
      extra: `Cumulative: ${Number(qa.identity_checks.cumulative_max_abs_residual).toExponential(2)}`
    }
  ];

  reviewRoot.innerHTML = "";
  for (const item of items) {
    const div = document.createElement("article");
    div.className = "review-item";
    div.innerHTML = `<p class="title">${item.title}</p><p class="main">${item.main}</p><p>${item.extra}</p>`;
    reviewRoot.appendChild(div);
  }
}

function renderChart(series) {
  const country = store.countries.find((c) => c.code === state.country);
  const industries = store.industriesByCountry.get(state.country) || [];
  const industry = industries.find((i) => i.code === state.industry);

  document.getElementById("chartTitle").textContent =
    state.mode === "yoy" ? "YoY Output Decomposition" : "Cumulative Output Decomposition";

  const first = series[0];
  const subtitleParts = [
    country ? country.name : "Unknown country",
    industry ? industry.name : "Unknown industry"
  ];
  if (state.mode === "cumulative" && first?.base_year !== null && first?.base_year !== undefined) {
    subtitleParts.push(`Base year: ${first.base_year}`);
  }
  document.getElementById("chartSubtitle").textContent = subtitleParts.join(" | ");

  if (!series.length) {
    Plotly.react(
      "mainChart",
      [],
      {
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "#f8fcfa",
        margin: { t: 24, r: 30, b: 45, l: 55 },
        xaxis: { title: "Year" },
        yaxis: { title: "Contribution (pp)" },
        annotations: [
          {
            x: 0.5,
            y: 0.5,
            xref: "paper",
            yref: "paper",
            text: "No data for this country-industry selection.",
            showarrow: false,
            font: { size: 14, color: "#4e6264" }
          }
        ]
      },
      { responsive: true, displayModeBar: false }
    );
    return;
  }

  const years = series.map((row) => row.year);
  const labor = series.map((row) => row.contrib_l);
  const capital = series.map((row) => row.contrib_k);
  const tfp = series.map((row) => row.contrib_tfp);
  const output = series.map((row) => row.g_y);

  const traces = [
    {
      x: years,
      y: labor,
      type: "scatter",
      mode: "lines",
      stackgroup: "decomposition",
      name: "Labor contribution",
      line: { color: COLORS.labor, width: 1.2 },
      fillcolor: "rgba(235, 106, 52, 0.65)",
      hovertemplate: "Labor: %{y:.2f} pp<br>Year: %{x}<extra></extra>"
    },
    {
      x: years,
      y: capital,
      type: "scatter",
      mode: "lines",
      stackgroup: "decomposition",
      name: "Capital contribution",
      line: { color: COLORS.capital, width: 1.2 },
      fillcolor: "rgba(38, 140, 133, 0.65)",
      hovertemplate: "Capital: %{y:.2f} pp<br>Year: %{x}<extra></extra>"
    },
    {
      x: years,
      y: tfp,
      type: "scatter",
      mode: "lines",
      stackgroup: "decomposition",
      name: "TFP contribution",
      line: { color: COLORS.tfp, width: 1.2 },
      fillcolor: "rgba(42, 75, 106, 0.65)",
      hovertemplate: "TFP: %{y:.2f} pp<br>Year: %{x}<extra></extra>"
    },
    {
      x: years,
      y: output,
      type: "scatter",
      mode: "lines",
      name: state.mode === "yoy" ? "Output growth" : "Cumulative output growth",
      line: { color: COLORS.output, width: 2.8 },
      hovertemplate: "Output: %{y:.2f} pp<br>Year: %{x}<extra></extra>"
    }
  ];

  const yAxisTitle =
    state.mode === "yoy"
      ? "YoY growth and contributions (pp)"
      : "Cumulative growth and contributions (pp)";

  const layout = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#f8fcfa",
    margin: { t: 24, r: 24, b: 45, l: 58 },
    xaxis: {
      title: "Year",
      showline: true,
      linecolor: "#9bb4ad",
      gridcolor: "#d8e6e1",
      tickmode: "auto",
      nticks: 12
    },
    yaxis: {
      title: yAxisTitle,
      showline: true,
      linecolor: "#9bb4ad",
      zeroline: true,
      zerolinecolor: "#96ada6",
      gridcolor: "#d8e6e1"
    },
    legend: {
      orientation: "h",
      y: 1.12,
      x: 0,
      bgcolor: "rgba(0,0,0,0)"
    },
    hovermode: "x unified"
  };

  Plotly.react("mainChart", traces, layout, {
    responsive: true,
    displayModeBar: false
  });
}

function render() {
  const series = getSeries();
  renderChart(series);
  renderMetrics(series);
}

async function init() {
  const [yoyRaw, cumulativeRaw, qa] = await Promise.all([
    d3.csv("outputs/solow_dashboard/mart_growth_yoy.csv"),
    d3.csv("outputs/solow_dashboard/mart_growth_cumulative.csv"),
    fetch("outputs/solow_dashboard/qa_summary.json").then((r) => r.json())
  ]);

  store.yoy = yoyRaw.map(normalizeYoY);
  store.cumulative = cumulativeRaw.map(normalizeCumulative);
  store.qa = qa;

  buildIndexes();
  initControls();
  renderReview();
  render();
}

init().catch((error) => {
  const msg = error instanceof Error ? error.message : String(error);
  const container = document.getElementById("mainChart");
  container.innerHTML = `<p style="padding:1rem;color:#a12020;">Failed to load dashboard data: ${msg}</p>`;
});
