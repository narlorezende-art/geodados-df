/* GeoDados DF — globo 3D com Medidores de Velocidade e previsão do tempo.
   Motor: CesiumJS (o mesmo do God's Eye View). */
"use strict";

/* ================= definições ================= */
const TYPES = {
  CE: { name: "Controlador eletrônico", color: "#C0801C", prefix: "KR" },
  RE: { name: "Redutor eletrônico de velocidade", color: "#4A90E0", prefix: "RE" },
  NM: { name: "Não metrológico", color: "#D15A7F", prefix: "FI" },
};
const DIRS = {
  "NORTE/SUL": "Norte → Sul", "SUL/NORTE": "Sul → Norte",
  "LESTE/OESTE": "Leste → Oeste", "OESTE/LESTE": "Oeste → Leste",
  "OUTRO": "Outro / via nomeada",
};
const PAGE = 120;

// escalas de cor do clima (valor → cor)
const RAMP_TEMP = [[8, "#3B4CC0"], [14, "#3A8EDB"], [18, "#43C1B0"], [22, "#A6D96A"], [26, "#FEE08B"], [30, "#F98E52"], [34, "#D73027"], [38, "#A50026"]];
const RAMP_RAIN = [[0.1, "#9BE7FF"], [0.5, "#5CC8FF"], [1, "#2E9BFF"], [2.5, "#2B5BFF"], [5, "#7B3FF2"], [10, "#D63FE0"], [20, "#FF4FA3"]];

const state = {
  items: [], byId: new Map(),
  types: new Set(Object.keys(TYPES)), dirs: new Set(Object.keys(DIRS)), ras: new Set(), q: "",
  selected: null, listLimit: PAGE, has3D: false, tilted: true, cluster: false, base: "sat",
  config: { googleMapsKey: "", cesiumIonToken: "", gdf: [] },
  gdfList: [], histIndex: 0, gdfLayer: null,
  wx: { data: null, hour: 0, on: { chuva: false, temp: false }, layers: {}, cache: {}, playing: null },
};
const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { const v = localStorage.getItem("gd:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("gd:" + k, JSON.stringify(v)); } catch { /* sem armazenamento */ } },
};
let viewer, ds, baseLayers = [], tileset = null, fallbackUsed = false, tileErrors = 0;

/* ================= início ================= */
window.addEventListener("DOMContentLoaded", boot);

async function boot() {
  startClock();
  let data;
  try {
    const [d, cfg, me] = await Promise.all([
      getJSON("/data/equipamentos.json"), getJSON("/api/config").catch(() => ({})), getJSON("/api/me").catch(() => null),
    ]);
    data = d; Object.assign(state.config, cfg);
    if (me && me.user) $("whoami").textContent = me.user;
  } catch (e) {
    if (e.status === 401) { location.href = "/login"; return; }
    $("loadingText").textContent = "Não foi possível carregar os dados. Recarregue a página.";
    return;
  }
  state.items = data;
  data.forEach((it) => { state.byId.set(it.id, it); state.ras.add(it.cra); });
  $("totCount").textContent = data.length;

  buildUI();
  try { await initGlobe(); } catch (e) { console.error(e); toast("O globo 3D não pôde ser iniciado neste navegador."); }
  $("loading").hidden = true;
  update();
  fitVisible(0);
  loadWeather();
  setInterval(loadWeather, 30 * 60 * 1000);
}

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!r.ok) { const e = new Error(r.statusText); e.status = r.status; try { e.body = await r.json(); } catch { /* */ } throw e; }
  return r.json();
}

function startClock() {
  const f = (tz, sec) => new Intl.DateTimeFormat("pt-BR", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: sec ? "2-digit" : undefined, hour12: false }).format(new Date());
  const tick = () => { $("clockBrt").textContent = f("America/Sao_Paulo", true) + " BRT"; $("clockUtc").textContent = f("UTC", false) + " UTC"; };
  tick(); setInterval(tick, 1000);
}

/* ================= ícones (opção A) ================= */
const PICTO = {
  CE: (c) => `<rect x="4" y="8" width="13" height="9" rx="1.6" fill="#fff"/><path d="M17 11l4-2v7l-4-2z" fill="#fff"/><circle cx="9.5" cy="12.5" r="2.4" fill="${c}"/><path d="M6 6.5h4" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>`,
  RE: () => `<circle cx="12" cy="12" r="8.6" fill="#fff" stroke="#D2231E" stroke-width="2.6"/><text x="12" y="15.4" font-family="Arial,Helvetica,sans-serif" font-weight="700" font-size="9.5" fill="#111" text-anchor="middle">60</text>`,
  NM: () => `<rect x="8" y="3.5" width="8" height="17" rx="2.4" fill="#fff"/><circle cx="12" cy="7.3" r="1.9" fill="#D2231E"/><circle cx="12" cy="12" r="1.9" fill="#E8A300"/><circle cx="12" cy="16.7" r="1.9" fill="#1E9E4A"/>`,
};
function iconSVG(k, { selected = false, shadow = true } = {}) {
  const color = TYPES[k].color;
  const pic = (s) => `<g transform="translate(${20 - 12 * s} ${20 - 12 * s}) scale(${s})">${PICTO[k](color)}</g>`;
  const frame = {
    CE: `<rect x="5.5" y="5.5" width="29" height="29" rx="6" fill="${color}" stroke="#fff" stroke-width="2.5"/>${pic(0.95)}`,
    RE: `<circle cx="20" cy="20" r="15" fill="${color}" stroke="#fff" stroke-width="2.5"/>${pic(0.95)}`,
    NM: `<rect x="8.5" y="8.5" width="23" height="23" rx="4" transform="rotate(45 20 20)" fill="${color}" stroke="#fff" stroke-width="2.5"/>${pic(0.78)}`,
  }[k];
  const halo = selected ? `<circle cx="20" cy="20" r="19.5" fill="#46D5E5" fill-opacity=".35"/>` : "";
  const f = shadow ? `<defs><filter id="sh" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="1.2" stdDeviation="1.2" flood-opacity=".5"/></filter></defs>` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40">${f}${halo}<g${shadow ? ' filter="url(#sh)"' : ""}>${frame}</g></svg>`;
}
const svgURL = (svg) => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
const icoHTML = (k) => `<span class="ico" aria-hidden="true">${iconSVG(k, { shadow: false })}</span>`;

function clusterIcon(n) {
  const c = document.createElement("canvas"); c.width = c.height = 96;
  const x = c.getContext("2d");
  x.beginPath(); x.arc(48, 48, 44, 0, Math.PI * 2); x.fillStyle = "rgba(70,213,229,.18)"; x.fill();
  x.beginPath(); x.arc(48, 48, 34, 0, Math.PI * 2); x.fillStyle = "rgba(9,14,19,.92)"; x.fill();
  x.lineWidth = 4; x.strokeStyle = "#46D5E5"; x.stroke();
  x.fillStyle = "#DCE7EE"; x.font = "600 32px 'IBM Plex Mono', monospace";
  x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(String(n), 48, 50);
  return c.toDataURL();
}

/* ================= globo ================= */
async function initGlobe() {
  const C = Cesium;
  if (state.config.cesiumIonToken) C.Ion.defaultAccessToken = state.config.cesiumIonToken;
  if (state.config.googleMapsKey) C.GoogleMaps.defaultApiKey = state.config.googleMapsKey;

  viewer = new C.Viewer("map", {
    baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
    navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
    infoBox: false, selectionIndicator: false, requestRenderMode: true, maximumRenderTimeChange: Infinity,
  });
  const scene = viewer.scene;
  scene.globe.baseColor = C.Color.fromCssColorString("#0B141B");
  scene.backgroundColor = C.Color.fromCssColorString("#05080B");
  scene.skyAtmosphere.show = true;
  scene.fog.enabled = true;
  viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

  setBase(store.get("base", "sat"));
  viewer.camera.setView({
    destination: C.Cartesian3.fromDegrees(-47.93, -16.28, 42000),
    orientation: { heading: 0, pitch: C.Math.toRadians(-42), roll: 0 },
  });

  ds = new C.CustomDataSource("medidores");
  await viewer.dataSources.add(ds);
  state.icons = {};
  for (const k of Object.keys(TYPES)) state.icons[k] = { n: svgURL(iconSVG(k)), s: svgURL(iconSVG(k, { selected: true })) };

  for (const it of state.items) {
    it.entity = ds.entities.add({
      id: it.id,
      position: C.Cartesian3.fromDegrees(it.lon, it.lat),
      billboard: {
        image: state.icons[it.t].n, width: 28, height: 28,
        heightReference: C.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scaleByDistance: new C.NearFarScalar(1500, 1.15, 120000, 0.7),
      },
      label: {
        text: it.id, show: false, font: "600 13px 'IBM Plex Mono', monospace",
        fillColor: C.Color.fromCssColorString("#DCE7EE"), outlineColor: C.Color.fromCssColorString("#05080B"), outlineWidth: 4,
        style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(0, -30),
        heightReference: C.HeightReference.CLAMP_TO_GROUND, disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  const cl = ds.clustering;
  cl.pixelRange = 38; cl.minimumClusterSize = 3; cl.enabled = false;
  const clusterIcons = new Map();
  cl.clusterEvent.addEventListener((entities, cluster) => {
    const n = entities.length;
    if (!clusterIcons.has(n)) clusterIcons.set(n, clusterIcon(n));
    cluster.label.show = false;
    cluster.billboard.show = true;
    cluster.billboard.image = clusterIcons.get(n);
    cluster.billboard.width = cluster.billboard.height = n >= 100 ? 46 : n >= 10 ? 38 : 32;
    cluster.billboard.verticalOrigin = C.VerticalOrigin.CENTER;
    cluster.billboard.disableDepthTestDistance = Number.POSITIVE_INFINITY;
    cluster.billboard.id = entities;
  });

  const handler = new C.ScreenSpaceEventHandler(scene.canvas);
  let raf = 0, lastMove = null;
  handler.setInputAction((m) => {
    lastMove = m.endPosition;
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; hover(lastMove); });
  }, C.ScreenSpaceEventType.MOUSE_MOVE);
  handler.setInputAction((c) => {
    const p = scene.pick(c.position);
    if (!p || !p.id) return;
    if (Array.isArray(p.id)) return zoomToEntities(p.id);
    if (p.id instanceof C.Entity && state.byId.has(p.id.id)) select(p.id.id, true);
  }, C.ScreenSpaceEventType.LEFT_CLICK);

  for (const ev of ["pointerdown", "wheel", "touchstart"]) scene.canvas.addEventListener(ev, () => stopOrbit(), { passive: true });
  viewer.camera.changed.addEventListener(updateAltitude);
  viewer.camera.moveEnd.addEventListener(updateAltitude);
  viewer.camera.percentageChanged = 0.05;
  updateAltitude();
}

function hover(pos) {
  const tip = $("tip");
  if (!pos || !viewer) return (tip.hidden = true);
  // posição do cursor na barra de status + clima no ponto
  const cart = viewer.camera.pickEllipsoid(pos, viewer.scene.globe.ellipsoid);
  if (cart) {
    const g = Cesium.Cartographic.fromCartesian(cart);
    const lat = Cesium.Math.toDegrees(g.latitude), lon = Cesium.Math.toDegrees(g.longitude);
    $("sbPos").textContent = `LAT ${fmtCoord(lat, "S", "N")}  LON ${fmtCoord(lon, "W", "E")}`;
    $("sbWx").textContent = wxAt(lat, lon) || "";
  }
  const p = viewer.scene.pick(pos);
  let html = "";
  if (p && Array.isArray(p.id)) html = `<b>${p.id.length}</b><span>medidores · clique para aproximar</span>`;
  else if (p && p.id && state.byId.has(p.id.id)) {
    const it = state.byId.get(p.id.id);
    html = `<b>${it.id}</b><span>${TYPES[it.t].name} · ${esc(it.ra)}</span>`;
  }
  viewer.scene.canvas.style.cursor = html ? "pointer" : "";
  if (!html) return (tip.hidden = true);
  tip.innerHTML = html;
  tip.style.left = pos.x + "px";
  tip.style.top = pos.y + "px";
  tip.hidden = false;
}
const fmtCoord = (v, neg, pos) => `${Math.abs(v).toFixed(5)}°${v < 0 ? neg : pos}`;

function updateAltitude() {
  const h = viewer.camera.positionCartographic.height;
  $("sbAlt").textContent = "ALT " + (h > 10000 ? (h / 1000).toFixed(1) + " km" : Math.round(h) + " m");
}

/* ================= mapas base ================= */
const DF_RECT = [-48.35, -16.10, -47.25, -15.45];   // mesmo recorte do servidor (gdf.py)
const BASE_NOME = {
  sat: "Satélite Esri", hib: "Satélite Esri + ruas", ruas: "Ruas Esri", escuro: "Mapa escuro Esri",
  osm: "© colaboradores do OpenStreetMap", gdf: "Foto aérea 2024 · SEDUH/GDF", offline: "Mapa offline",
};
let gdfErrors = 0, gdfWarned = false;

function esriProvider(svc, max = 19) {
  return new Cesium.UrlTemplateImageryProvider({
    url: `https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`,
    maximumLevel: max, credit: "Esri, Maxar, Earthstar Geographics, colaboradores do OpenStreetMap",
  });
}

// Fotos aéreas do GDF passam pelo nosso servidor Python (/gdf/...), que já entrega no formato do mapa
function gdfProvider(servico) {
  const prov = new Cesium.UrlTemplateImageryProvider({
    url: `/gdf/${servico}/{z}/{x}/{y}`,
    rectangle: Cesium.Rectangle.fromDegrees(...DF_RECT),
    minimumLevel: 8, maximumLevel: 21,
    credit: "Fotos aéreas e imagens © SEDUH/GDF — IDE-DF",
  });
  prov.errorEvent.addEventListener(() => {
    gdfErrors++;
    if (gdfErrors >= 10 && !gdfWarned) {
      gdfWarned = true;
      toast("O servidor de imagens do GDF está lento ou fora do ar. Fora das áreas carregadas aparece o satélite Esri.");
    }
  });
  return prov;
}

function setBase(key) {
  const C = Cesium, L = viewer.imageryLayers;
  if ((key === "gdf" || key === "hist") && !state.gdfList.length) key = "sat";
  baseLayers.forEach((l) => L.remove(l, true)); baseLayers = [];
  tileErrors = 0; gdfErrors = 0; gdfWarned = false;
  const add = (prov, watch = true) => { if (watch) watchErrors(prov); const l = L.addImageryProvider(prov, baseLayers.length); baseLayers.push(l); return l; };

  if (key === "sat") add(esriProvider("World_Imagery"));
  if (key === "hib") { add(esriProvider("World_Imagery")); add(esriProvider("Reference/World_Transportation", 18)); add(esriProvider("Reference/World_Boundaries_and_Places", 18)); }
  if (key === "ruas") add(esriProvider("World_Street_Map"));
  if (key === "escuro") { add(esriProvider("Canvas/World_Dark_Gray_Base", 16)); add(esriProvider("Canvas/World_Dark_Gray_Reference", 16)); }
  if (key === "osm") add(new C.UrlTemplateImageryProvider({ url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", maximumLevel: 19, credit: "© colaboradores do OpenStreetMap" }));
  if (key === "gdf" || key === "hist") {
    add(esriProvider("World_Imagery"), false);   // fundo fora do DF (opcional: se falhar, não troca o mapa)
    const svc = key === "gdf" ? "FOTO_AEREA_2024" : state.gdfList[state.histIndex].id;
    state.gdfLayer = add(gdfProvider(svc), false);
  } else state.gdfLayer = null;
  if (key === "offline") {
    const lyr = C.ImageryLayer.fromProviderAsync(C.TileMapServiceImageryProvider.fromUrl(C.buildModuleUrl("Assets/Textures/NaturalEarthII")));
    L.add(lyr, 0); baseLayers.push(lyr);
  }
  state.base = key;
  if (key !== "offline") store.set("base", key);
  document.querySelectorAll("#baseSeg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.base === key)));
  $("histBar").hidden = key !== "hist";
  if (key === "hist") showHistLabel();
  $("sbBase").textContent = key === "hist" ? histName() : BASE_NOME[key];
  viewer.scene.requestRender();
}

const histName = () => { const g = state.gdfList[state.histIndex]; return `${g.tipo} ${g.ano} · SEDUH/GDF`; };
function showHistLabel() {
  const g = state.gdfList[state.histIndex];
  $("histYear").value = state.histIndex;
  $("histAno").textContent = g.ano;
  $("histTipo").textContent = g.tipo;
  $("histPrev").disabled = state.histIndex === 0;
  $("histNext").disabled = state.histIndex === state.gdfList.length - 1;
}

// Troca o ano sem piscar: a foto nova entra por cima e a antiga sai depois
let histTimer;
function setHistYear(i) {
  i = Math.max(0, Math.min(state.gdfList.length - 1, i));
  state.histIndex = i;
  store.set("histIndex", i);
  showHistLabel();
  $("sbBase").textContent = histName();
  clearTimeout(histTimer);
  histTimer = setTimeout(() => {
    if (state.base !== "hist" || !viewer) return;
    const L = viewer.imageryLayers, old = state.gdfLayer;
    gdfErrors = 0; gdfWarned = false;
    const layer = L.addImageryProvider(gdfProvider(state.gdfList[state.histIndex].id), baseLayers.length);
    baseLayers.push(layer);
    state.gdfLayer = layer;
    if (old) setTimeout(() => { L.remove(old, true); baseLayers = baseLayers.filter((l) => l !== old); viewer.scene.requestRender(); }, 1500);
    viewer.scene.requestRender();
  }, 250);
}

function watchErrors(prov) {
  prov.errorEvent.addEventListener(() => {
    tileErrors++;
    if (tileErrors === 12 && !fallbackUsed) {
      fallbackUsed = true;
      setBase("offline");
      toast("O mapa base não respondeu. Mostrando o mapa offline; tente outro mapa base no canto superior direito.");
    }
  });
}

/* ================= 3D ================= */
async function toggle3D() {
  const C = Cesium, btn = $("btn3d"), scene = viewer.scene;
  if (!state.has3D) {
    btn.disabled = true; btn.textContent = "Carregando…";
    try {
      if (state.config.googleMapsKey) {
        tileset = await C.createGooglePhotorealistic3DTileset({ key: state.config.googleMapsKey });
        scene.globe.show = false;
      } else {
        scene.setTerrain(C.Terrain.fromWorldTerrain());
        tileset = await C.createOsmBuildingsAsync();
      }
      scene.primitives.add(tileset);
      state.has3D = true;
      if (state.config.googleMapsKey && (state.wx.on.chuva || state.wx.on.temp)) toast("As camadas de clima ficam ocultas enquanto os prédios fotorrealistas estão ligados.");
    } catch (e) {
      console.error(e);
      toast("Não foi possível carregar os prédios 3D. Confira a chave configurada no Render.");
    }
    btn.disabled = false; btn.textContent = "3D";
  } else {
    if (tileset) { scene.primitives.remove(tileset); tileset = null; }
    scene.globe.show = true;
    viewer.terrainProvider = new C.EllipsoidTerrainProvider();
    state.has3D = false;
  }
  btn.setAttribute("aria-pressed", String(state.has3D));
  document.querySelectorAll("#baseSeg button").forEach((b) => {
    b.disabled = state.has3D && !!state.config.googleMapsKey;
    b.title = b.disabled ? "Desligue Prédios 3D para trocar o mapa base" : "";
  });
  scene.requestRender();
}

/* ================= câmera ================= */
const groundHeightGuess = () => (state.has3D ? 1100 : 0);
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);

async function groundHeightAt(lon, lat) {
  if (!state.has3D) return 0;
  const C = Cesium, carto = C.Cartographic.fromDegrees(lon, lat);
  try {
    const [r] = tileset && state.config.googleMapsKey
      ? await withTimeout(viewer.scene.sampleHeightMostDetailed([carto]), 2500)
      : await withTimeout(C.sampleTerrainMostDetailed(viewer.terrainProvider, [carto]), 2500);
    if (r && Number.isFinite(r.height)) return r.height;
  } catch { /* usa estimativa */ }
  return 1100;
}

async function flyToItem(it) {
  const C = Cesium, h = await groundHeightAt(it.lon, it.lat);
  if (state.selected !== it.id) return;                 // outro medidor foi escolhido enquanto media o chão
  placeMarkerFx(it, h);
  stopOrbit();
  const center = C.Cartesian3.fromDegrees(it.lon, it.lat, h + LIFT / 2);
  const pitch = C.Math.toRadians(state.tilted ? -32 : -89.9), range = state.tilted ? 420 : 700;
  viewer.camera.flyToBoundingSphere(new C.BoundingSphere(center, 5), {
    offset: new C.HeadingPitchRange(viewer.camera.heading, pitch, range),
    duration: 1.6,
    complete: () => { if (state.selected === it.id && !reduceMotion()) startOrbit(center, pitch, range); updateOrbitBtn(); },
  });
}

/* ---------- destaque do medidor selecionado: ícone elevado + haste + alvo no chão ---------- */
const LIFT = 30;                                        // metros acima do chão
const CYAN = () => Cesium.Color.fromCssColorString("#46D5E5");

function placeMarkerFx(it, h) {
  const C = Cesium;
  clearMarkerFx();
  const ground = C.Cartesian3.fromDegrees(it.lon, it.lat, h);
  const top = C.Cartesian3.fromDegrees(it.lon, it.lat, h + LIFT);
  state.fx = [
    viewer.entities.add({            // haste luminosa do chão até o ícone
      polyline: {
        positions: [ground, top], width: 5, arcType: C.ArcType.NONE,
        material: new C.PolylineGlowMaterialProperty({ glowPower: 0.25, color: CYAN() }),
        depthFailMaterial: new C.PolylineGlowMaterialProperty({ glowPower: 0.25, color: CYAN().withAlpha(0.45) }),
      },
    }),
    viewer.entities.add({            // alvo no chão marcando a coordenada exata
      position: ground,
      ellipse: { semiMajorAxis: 6, semiMinorAxis: 6, material: CYAN().withAlpha(0.22), classificationType: C.ClassificationType.BOTH },
      point: {
        pixelSize: 8, color: CYAN(), outlineColor: C.Color.fromCssColorString("#05080B"), outlineWidth: 2,
        heightReference: C.HeightReference.CLAMP_TO_GROUND, disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    }),
  ];
  // o próprio ícone sobe e deixa a via livre
  const e = it.entity;
  e.position = top;
  e.billboard.heightReference = C.HeightReference.NONE;
  e.label.heightReference = C.HeightReference.NONE;
  viewer.scene.requestRender();
}

function clearMarkerFx() {
  (state.fx || []).forEach((e) => viewer.entities.remove(e));
  state.fx = [];
}

/* ---------- órbita lenta em volta do ponto (uma volta a cada ~90 s) ---------- */
const ORBIT_SECONDS = 90;
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let orbit = null;

function startOrbit(center, pitch, range) {
  const C = Cesium, cam = viewer.camera;
  stopOrbit();
  orbit = { center, pitch, range, heading: cam.heading, last: performance.now(), raf: 0 };
  const step = (t) => {
    if (!orbit) return;
    const dt = Math.min(0.25, (t - orbit.last) / 1000); orbit.last = t;
    orbit.heading += (2 * Math.PI / ORBIT_SECONDS) * dt;
    cam.lookAt(orbit.center, new C.HeadingPitchRange(orbit.heading, orbit.pitch, orbit.range));
    viewer.scene.requestRender();
    orbit.raf = requestAnimationFrame(step);
  };
  orbit.raf = requestAnimationFrame(step);
  updateOrbitBtn();
}

function stopOrbit() {
  if (!orbit) return;
  cancelAnimationFrame(orbit.raf);
  state.lastOrbit = { center: orbit.center, pitch: orbit.pitch, range: orbit.range };
  orbit = null;
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);   // devolve a navegação livre
  updateOrbitBtn();
}

function toggleOrbit() {
  if (orbit) return stopOrbit();
  const it = state.byId.get(state.selected); if (!it) return;
  if (state.lastOrbit) {
    // retoma a partir da posição atual da câmera, mantendo distância e inclinação
    const C = Cesium, cam = viewer.camera, c = state.lastOrbit.center;
    const range = Math.max(150, C.Cartesian3.distance(cam.positionWC, c));
    startOrbit(c, Math.min(-0.2, cam.pitch), range);
  } else flyToItem(it);
}

function updateOrbitBtn() {
  const b = $("cOrbit"); if (!b) return;
  b.setAttribute("aria-pressed", String(!!orbit));
  b.textContent = orbit ? "Pausar órbita" : "Girar em volta";
}

function fitVisible(duration = 1.4) {
  if (!viewer) return;
  stopOrbit();
  const C = Cesium, h = groundHeightGuess(), vis = visibleItems();
  if (!vis.length) return;
  const bs = C.BoundingSphere.fromPoints(vis.map((it) => C.Cartesian3.fromDegrees(it.lon, it.lat, h)));
  viewer.camera.flyToBoundingSphere(bs, {
    offset: new C.HeadingPitchRange(0, C.Math.toRadians(state.tilted ? -48 : -89.9), Math.max(bs.radius * 2.4, 1200)), duration,
  });
}

function zoomToEntities(ents) {
  const C = Cesium, h = groundHeightGuess();
  const bs = C.BoundingSphere.fromPoints(ents.map((e) => { const it = state.byId.get(e.id); return C.Cartesian3.fromDegrees(it.lon, it.lat, h); }));
  viewer.camera.flyToBoundingSphere(bs, { offset: new C.HeadingPitchRange(viewer.camera.heading, C.Math.toRadians(state.tilted ? -50 : -89.9), Math.max(bs.radius * 3, 900)), duration: 1.2 });
}

function toggleTilt() {
  const C = Cesium, scene = viewer.scene, cam = viewer.camera;
  if (orbit) {                       // em órbita: só muda a inclinação e continua girando
    state.tilted = !state.tilted;
    $("btnTilt").setAttribute("aria-pressed", String(state.tilted));
    $("btnTilt").textContent = state.tilted ? "Inclinada" : "De cima";
    orbit.pitch = C.Math.toRadians(state.tilted ? -32 : -89.9);
    return;
  }
  state.tilted = !state.tilted;
  $("btnTilt").setAttribute("aria-pressed", String(state.tilted));
  $("btnTilt").textContent = state.tilted ? "Inclinada" : "De cima";
  const center = new C.Cartesian2(scene.canvas.clientWidth / 2, scene.canvas.clientHeight / 2);
  let target = state.has3D ? scene.pickPosition(center) : undefined;
  if (!target) target = cam.pickEllipsoid(center, scene.globe.ellipsoid);
  if (!target) return fitVisible();
  cam.flyToBoundingSphere(new C.BoundingSphere(target, 1), {
    offset: new C.HeadingPitchRange(cam.heading, C.Math.toRadians(state.tilted ? -42 : -89.9), C.Cartesian3.distance(cam.positionWC, target)), duration: 1.0,
  });
}

/* ================= previsão do tempo ================= */
async function loadWeather() {
  try {
    const d = await getJSON("/api/clima");
    state.wx.data = d; state.wx.cache = {};
    const n = d.horas.length;
    $("wxHour").max = n - 1;
    if (state.wx.hour > n - 1) state.wx.hour = 0;
    const hora = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" }).format(new Date(d.atualizado));
    $("climaStatus").textContent = d.desatualizado ? "antiga" : "48 h";
    $("wxNote").textContent = d.desatualizado
      ? `A fonte não respondeu; mostrando a última previsão (atualizada às ${hora}).`
      : `Fonte: Open-Meteo · grade de ~9 km · atualizada às ${hora}`;
    $("wxNote").classList.toggle("warn", !!d.desatualizado);
    setHour(state.wx.hour);
  } catch (e) {
    $("climaStatus").textContent = "off";
    $("wxNote").textContent = (e.body && e.body.erro) || "Previsão indisponível no momento. Nova tentativa em 30 minutos.";
    $("wxNote").classList.add("warn");
  }
}

function setHour(i) {
  const d = state.wx.data; if (!d) return;
  state.wx.hour = i;
  $("wxHour").value = i;
  const [data, hm] = d.horas[i].split("T");
  const dt = new Date(data + "T12:00:00");
  const dia = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" }).format(dt).replace(".", "");
  $("wxWhen").textContent = `${dia} · ${hm.slice(0, 2)}h`;
  $("wxRel").textContent = i === 0 ? "agora" : `+${i} h`;
  for (const k of ["chuva", "temp"]) if (state.wx.on[k]) drawWx(k);
  if (state.selected) fillCardWx(state.byId.get(state.selected));
  rainSummary();
}

// Diz em texto o que a camada de chuva está mostrando (inclusive quando não há chuva nenhuma)
function rainSummary() {
  const d = state.wx.data, el = $("rainStatus");
  if (!d) { el.textContent = ""; return; }
  const h = state.wx.hour, mm = (v) => v.toFixed(1).replace(".", ",");
  const maxAt = (k) => Math.max(0, ...d.chuva[k].filter((v) => v != null));
  const agora = maxAt(h);
  if (agora >= 0.1) {
    const area = Math.round(d.chuva[h].filter((v) => v >= 0.1).length / d.chuva[h].length * 100);
    el.innerHTML = `<span>Chuva prevista em <b>${area}%</b> do DF nesta hora · máx. <b>${mm(agora)} mm/h</b></span>`;
    return;
  }
  let prox = -1;
  for (let k = h + 1; k < d.horas.length; k++) if (maxAt(k) >= 0.1) { prox = k; break; }
  if (prox >= 0) {
    const [dia, hm] = d.horas[prox].split("T");
    const rot = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" }).format(new Date(dia + "T12:00:00")).replace(".", "");
    el.innerHTML = `<span>Sem chuva nesta hora. Próxima chuva prevista: <b>${rot} · ${hm.slice(0, 2)}h</b></span><button type="button" data-go="${prox}">Ir</button>`;
    return;
  }
  const pmax = Math.max(0, ...d.prob.flat().filter((v) => v != null));
  el.innerHTML = `<span>Sem chuva prevista no DF nas próximas ${d.horas.length} h. Chance máxima de chuva: <b>${pmax}%</b>.</span>`;
}

function drawWx(kind) {
  const d = state.wx.data;
  if (!d || !viewer) return;
  const key = kind + ":" + state.wx.hour;
  let url = state.wx.cache[key];
  if (!url) { url = renderField(kind, d, state.wx.hour); state.wx.cache[key] = url; }
  const C = Cesium, L = viewer.imageryLayers;
  const old = state.wx.layers[kind];
  const [w, s, e, n] = d.bbox;
  const layer = C.ImageryLayer.fromProviderAsync(
    C.SingleTileImageryProvider.fromUrl(url, { rectangle: C.Rectangle.fromDegrees(w, s, e, n) }),
  );
  layer.alpha = Number($(kind === "chuva" ? "opChuva" : "opTemp").value) / 100;
  // temperatura por baixo, chuva por cima
  if (kind === "temp" && state.wx.layers.chuva) L.add(layer, L.indexOf(state.wx.layers.chuva)); else L.add(layer);
  state.wx.layers[kind] = layer;
  if (old) setTimeout(() => { L.remove(old, true); viewer.scene.requestRender(); }, 250); // troca sem piscar
  viewer.scene.requestRender();
}

function removeWx(kind) {
  const l = state.wx.layers[kind];
  if (l && viewer) { viewer.imageryLayers.remove(l, true); viewer.scene.requestRender(); }
  delete state.wx.layers[kind];
}

// Interpola a grade (suave, com textura de nuvem) e pinta numa imagem transparente
function renderField(kind, d, h) {
  const vals = (kind === "chuva" ? d.chuva : d.temp)[h];
  const probs = d.prob[h];
  const NX = d.nx, NY = d.ny, W = 512, H = Math.round(512 * NY / NX);
  const c = document.createElement("canvas"); c.width = W; c.height = H;
  const x = c.getContext("2d"), img = x.createImageData(W, H), px = img.data;
  const ramp = kind === "chuva" ? RAMP_RAIN : RAMP_TEMP;
  const noise = kind === "chuva" ? cloudNoise(W, H) : null;
  const sm = (t) => t * t * (3 - 2 * t);
  for (let y = 0; y < H; y++) {
    const gy = y / (H - 1) * (NY - 1), j0 = Math.min(NY - 2, Math.floor(gy)), ty = sm(gy - j0);
    for (let xx = 0; xx < W; xx++) {
      const gx = xx / (W - 1) * (NX - 1), i0 = Math.min(NX - 2, Math.floor(gx)), tx = sm(gx - i0);
      const a = vals[j0 * NX + i0], b = vals[j0 * NX + i0 + 1], cc = vals[(j0 + 1) * NX + i0], dd = vals[(j0 + 1) * NX + i0 + 1];
      if (a == null || b == null || cc == null || dd == null) continue;
      let v = (a * (1 - tx) + b * tx) * (1 - ty) + (cc * (1 - tx) + dd * tx) * ty;
      let alpha;
      if (kind === "chuva") {
        v *= 0.75 + 0.5 * noise[y * W + xx];           // textura de nuvem
        if (v < 0.04) {
          // sem volume previsto: mostra, em listras suaves, onde a chance de chuva é de 30% ou mais
          const pa = probs[j0 * NX + i0], pb = probs[j0 * NX + i0 + 1], pc = probs[(j0 + 1) * NX + i0], pd = probs[(j0 + 1) * NX + i0 + 1];
          if (pa == null || pb == null || pc == null || pd == null) continue;
          const p = (pa * (1 - tx) + pb * tx) * (1 - ty) + (pc * (1 - tx) + pd * tx) * ty;
          if (p < 30) continue;
          const stripe = ((xx + y) % 10) < 5 ? 1 : 0.4;
          const edge = Math.min(xx, W - 1 - xx, y, H - 1 - y) / (W * 0.08);
          const o = (y * W + xx) * 4;
          px[o] = 150; px[o + 1] = 190; px[o + 2] = 230;
          px[o + 3] = Math.round((0.14 + 0.3 * Math.min(1, (p - 30) / 60)) * stripe * Math.min(1, edge) * 255);
          continue;
        }
        const fade = Math.min(1, (v - 0.04) / 0.3);          // borda suave da mancha de chuva
        alpha = Math.min(0.85, 0.35 + Math.log10(1 + v) * 0.45) * fade * fade;
      } else alpha = 0.72;
      const edge = Math.min(xx, W - 1 - xx, y, H - 1 - y) / (W * 0.08); // borda esmaecida
      alpha *= Math.min(1, edge);
      const [r, g, bl] = rampColor(ramp, v);
      const o = (y * W + xx) * 4;
      px[o] = r; px[o + 1] = g; px[o + 2] = bl; px[o + 3] = Math.round(alpha * 255);
    }
  }
  x.putImageData(img, 0, 0);
  return c.toDataURL("image/png");
}

let _noise = null;
function cloudNoise(W, H) {
  if (_noise && _noise.W === W && _noise.H === H) return _noise.v;
  const v = new Float32Array(W * H);
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (const [cell, amp] of [[64, 0.55], [24, 0.3], [9, 0.15]]) {
    const gw = Math.ceil(W / cell) + 2, gh = Math.ceil(H / cell) + 2, g = Array.from({ length: gw * gh }, rnd);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const fx = x / cell, fy = y / cell, i = Math.floor(fx), j = Math.floor(fy), tx = fx - i, ty = fy - j;
      const s = (t) => t * t * (3 - 2 * t);
      const a = g[j * gw + i], b = g[j * gw + i + 1], c = g[(j + 1) * gw + i], d = g[(j + 1) * gw + i + 1];
      v[y * W + x] += amp * ((a * (1 - s(tx)) + b * s(tx)) * (1 - s(ty)) + (c * (1 - s(tx)) + d * s(tx)) * s(ty));
    }
  }
  _noise = { W, H, v };
  return v;
}

function rampColor(ramp, v) {
  const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  if (v <= ramp[0][0]) return hex(ramp[0][1]);
  for (let i = 1; i < ramp.length; i++) {
    if (v <= ramp[i][0]) {
      const [v0, c0] = ramp[i - 1], [v1, c1] = ramp[i], t = (v - v0) / (v1 - v0);
      const a = hex(c0), b = hex(c1);
      return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * t));
    }
  }
  return hex(ramp[ramp.length - 1][1]);
}

function sampleWx(lat, lon, h = state.wx.hour) {
  const d = state.wx.data; if (!d) return null;
  const [w, s, e, n] = d.bbox;
  if (lon < w || lon > e || lat < s || lat > n) return null;
  const gx = (lon - w) / (e - w) * (d.nx - 1), gy = (n - lat) / (n - s) * (d.ny - 1);
  const i = Math.round(gx), j = Math.round(gy), k = j * d.nx + i;
  return { t: d.temp[h][k], r: d.chuva[h][k], p: d.prob[h][k] };
}

function wxAt(lat, lon) {
  if (!state.wx.on.chuva && !state.wx.on.temp) return "";
  const v = sampleWx(lat, lon); if (!v) return "";
  const parts = [];
  if (state.wx.on.temp && v.t != null) parts.push(`TEMP ${v.t.toFixed(1).replace(".", ",")} °C`);
  if (state.wx.on.chuva && v.r != null) parts.push(`CHUVA ${v.r.toFixed(1).replace(".", ",")} mm/h · ${v.p ?? "–"}%`);
  return parts.join("   ");
}

function fillCardWx(it) {
  const v = it && sampleWx(it.lat, it.lon);
  $("cWxRow").hidden = !v;
  if (v) $("cWx").textContent = `${$("wxWhen").textContent}: ${v.t?.toFixed(1).replace(".", ",")} °C · chuva ${v.r?.toFixed(1).replace(".", ",")} mm/h (${v.p ?? "–"}%)`;
}

function drawRamp(el, ramp, ticks, unitFmt) {
  const lo = ramp[0][0], hi = ramp[ramp.length - 1][0];
  const pos = (v) => (el.id === "rampChuva" ? Math.log10(1 + v) / Math.log10(1 + hi) : (v - lo) / (hi - lo)) * 100;
  const stops = ramp.map(([v, c]) => `${c} ${pos(v).toFixed(1)}%`).join(",");
  el.innerHTML = `<div class="bar" style="background:linear-gradient(90deg,${stops})"></div>
    <div class="ticks">${ticks.map((t) => `<span>${unitFmt(t)}</span>`).join("")}</div>`;
}

function toggleWx(kind, on) {
  state.wx.on[kind] = on;
  store.set("wx:" + kind, on);
  document.querySelector(`.wx[data-wx="${kind}"]`).classList.toggle("on", on);
  if (on) {
    if (!state.wx.data) toast("A previsão ainda está carregando…");
    else drawWx(kind);
  } else removeWx(kind);
  if (!state.wx.on.chuva && !state.wx.on.temp) $("sbWx").textContent = "";
}

function togglePlay() {
  const b = $("wxPlay");
  if (state.wx.playing) {
    clearInterval(state.wx.playing); state.wx.playing = null;
    b.setAttribute("aria-pressed", "false"); b.setAttribute("aria-label", "Animar previsão");
    b.innerHTML = `<svg viewBox="0 0 16 16"><path d="M5 3.5v9l7-4.5z"/></svg>`;
    return;
  }
  if (!state.wx.on.chuva && !state.wx.on.temp) { $("swChuva").checked = true; toggleWx("chuva", true); }
  b.setAttribute("aria-pressed", "true"); b.setAttribute("aria-label", "Pausar");
  b.innerHTML = `<svg viewBox="0 0 16 16"><path d="M4.5 3.5h2.5v9H4.5zM9 3.5h2.5v9H9z"/></svg>`;
  state.wx.playing = setInterval(() => {
    const max = Number($("wxHour").max);
    setHour(state.wx.hour >= max ? 0 : state.wx.hour + 1);
  }, 900);
}

/* ================= filtros ================= */
function matches(it, skip) {
  if (skip !== "t" && !state.types.has(it.t)) return false;
  if (skip !== "s" && !state.dirs.has(it.s)) return false;
  if (skip !== "ra" && !state.ras.has(it.cra)) return false;
  if (state.q) {
    const hay = it._hay || (it._hay = norm(`${it.id} ${it.end} ${it.ra}`));
    if (!state.q.split(" ").every((w) => hay.includes(w))) return false;
  }
  return true;
}
const visibleItems = () => state.items.filter((it) => matches(it));
const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const toggleSet = (set, v) => (set.has(v) ? set.delete(v) : set.add(v));

/* ================= interface ================= */
function buildUI() {
  // abas
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  // painel rebatível + transparência
  const panel = $("panel");
  const setCollapsed = (c) => {
    panel.classList.toggle("collapsed", c);
    $("panelOpen").hidden = !c;
    store.set("collapsed", c);
  };
  $("panelClose").onclick = () => setCollapsed(true);
  $("panelOpen").onclick = () => setCollapsed(false);
  setCollapsed(store.get("collapsed", false));
  // transparência vale para o painel inteiro (caixas e textos); com o mouse em cima ele fica sólido
  const transp = store.get("transp", 35);
  $("panelAlpha").value = transp;
  panel.style.setProperty("--po", 1 - transp / 100);
  $("panelAlpha").addEventListener("input", (e) => { panel.style.setProperty("--po", 1 - e.target.value / 100); store.set("transp", Number(e.target.value)); });

  // árvore: Medidores de Velocidade → 3 tipos
  $("subMedidores").innerHTML = Object.entries(TYPES).map(([k, t]) => `
    <label class="sub" data-t="${k}" for="sw-${k}">
      ${icoHTML(k)}
      <span class="s-name">${t.name}<small>prefixo ${t.prefix}</small></span>
      <span class="s-n" data-n>0</span>
      <span class="switch"><input type="checkbox" id="sw-${k}" checked><span></span></span>
    </label>`).join("");
  $("subMedidores").addEventListener("change", (e) => {
    const k = e.target.id.replace("sw-", "");
    e.target.checked ? state.types.add(k) : state.types.delete(k);
    update();
  });
  $("swMedidores").addEventListener("change", (e) => {
    state.types = e.target.checked ? new Set(Object.keys(TYPES)) : new Set();
    update();
  });
  document.querySelectorAll(".twisty").forEach((b) => b.addEventListener("click", () => {
    const open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", String(open));
    $(b.getAttribute("aria-controls")).hidden = !open;
  }));

  // clima
  drawRamp($("rampChuva"), RAMP_RAIN, [0.1, 1, 5, 20], (v) => String(v).replace(".", ",") + (v === 20 ? "+" : ""));
  drawRamp($("rampTemp"), RAMP_TEMP, [8, 18, 28, 38], (v) => v + "°");
  for (const [kind, sw, op] of [["chuva", "swChuva", "opChuva"], ["temp", "swTemp", "opTemp"]]) {
    $(sw).addEventListener("change", (e) => toggleWx(kind, e.target.checked));
    $(op).addEventListener("input", (e) => {
      const l = state.wx.layers[kind]; if (l) { l.alpha = e.target.value / 100; viewer.scene.requestRender(); }
    });
    if (store.get("wx:" + kind, false)) { $(sw).checked = true; state.wx.on[kind] = true; document.querySelector(`.wx[data-wx="${kind}"]`).classList.add("on"); }
  }
  $("wxHour").addEventListener("input", (e) => setHour(Number(e.target.value)));
  $("rainStatus").addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b) setHour(Number(b.dataset.go)); });
  $("wxPlay").onclick = togglePlay;

  // sentidos
  $("dirChips").innerHTML = Object.entries(DIRS).map(([k, l]) =>
    `<button type="button" class="chip" data-s="${k}" aria-pressed="true">${l}<b data-n>0</b></button>`).join("");
  $("dirChips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    toggleSet(state.dirs, b.dataset.s); update();
  });

  // RAs
  const ras = new Map();
  state.items.forEach((it) => ras.set(it.cra, { cra: it.cra, ra: it.ra, n: (ras.get(it.cra)?.n || 0) + 1 }));
  $("raList").innerHTML = [...ras.values()].sort((a, b) => b.n - a.n || a.cra - b.cra).map((r) => `
    <li data-cra="${r.cra}">
      <label for="ra-${r.cra}">
        <input type="checkbox" id="ra-${r.cra}" value="${r.cra}" checked>
        <span class="ra-name" title="RA ${String(r.cra).padStart(2, "0")} · ${esc(r.ra)}"><span class="code">${String(r.cra).padStart(2, "0")}</span>${esc(r.ra)}</span>
        <span class="ra-bar"><i></i></span>
        <span class="ra-n">0</span>
      </label>
    </li>`).join("");
  $("raList").addEventListener("change", (e) => {
    const v = Number(e.target.value);
    e.target.checked ? state.ras.add(v) : state.ras.delete(v); update();
  });
  $("raAll").onclick = () => { state.items.forEach((it) => state.ras.add(it.cra)); update(); };
  $("raNone").onclick = () => { state.ras.clear(); update(); };

  // busca
  let t;
  $("q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = norm(e.target.value.trim()).replace(/\s+/g, " "); update(); }, 120);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); $("panel").classList.contains("collapsed") && $("panelOpen").click(); showTab("filtros"); $("q").focus(); }
    if (e.key === "Escape") closeCard();
  });

  // lista
  $("results").addEventListener("click", (e) => {
    const b = e.target.closest("[data-id]");
    if (b) return select(b.dataset.id, true);
    if (e.target.closest(".more")) { state.listLimit += PAGE; renderList(); }
  });
  $("exportCsv").onclick = exportCsv;

  // mapa base e visualização
  $("baseSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-base]"); if (!b || !viewer || b.disabled) return;
    fallbackUsed = false; setBase(b.dataset.base);
  });
  // fotos do GDF: lista de anos vem do servidor
  state.gdfList = state.config.gdf || [];
  if (!state.gdfList.length) document.querySelectorAll('#baseSeg [data-base="gdf"], #baseSeg [data-base="hist"]').forEach((b) => (b.hidden = true));
  else {
    const idx1991 = state.gdfList.findIndex((g) => g.ano === "1991");
    state.histIndex = Math.min(state.gdfList.length - 1, store.get("histIndex", idx1991 >= 0 ? idx1991 : 0));
    $("histYear").max = state.gdfList.length - 1;
    $("histYear").addEventListener("input", (e) => setHistYear(Number(e.target.value)));
    $("histPrev").onclick = () => setHistYear(state.histIndex - 1);
    $("histNext").onclick = () => setHistYear(state.histIndex + 1);
  }

  // 3D só aparece quando há chave configurada no Render
  const can3D = state.config.googleMapsKey || state.config.cesiumIonToken;
  $("btn3d").hidden = !can3D;
  $("btn3d").disabled = !can3D;
  $("btn3d").title = can3D
    ? (state.config.googleMapsKey ? "Prédios fotorrealistas do Google" : "Relevo e prédios (Cesium ion)")
    : "Para ativar, configure GOOGLE_MAPS_KEY ou CESIUM_ION_TOKEN no Render (veja o README)";
  $("btn3d").onclick = () => viewer && toggle3D();
  $("btnTilt").onclick = () => viewer && toggleTilt();
  $("btnFit").onclick = () => fitVisible();
  $("btnCluster").onclick = () => {
    state.cluster = !state.cluster;
    $("btnCluster").setAttribute("aria-pressed", String(state.cluster));
    if (ds) { ds.clustering.enabled = state.cluster; viewer.scene.requestRender(); }
  };

  // ficha
  $("cardClose").onclick = closeCard;
  $("cOrbit").onclick = () => viewer && toggleOrbit();
  $("cCopy").onclick = async () => {
    const txt = $("cXY").textContent;
    try { await navigator.clipboard.writeText(txt); toast("Coordenadas copiadas."); }
    catch { const r = document.createRange(); r.selectNodeContents($("cXY")); getSelection().removeAllRanges(); getSelection().addRange(r); }
  };
}

function showTab(tab) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll(".tabpane").forEach((p) => { p.hidden = p.dataset.pane !== tab; });
}

function update() {
  const vis = visibleItems(), n = vis.length;
  $("visCount").textContent = n;
  $("visTop").textContent = n;

  const byT = { CE: 0, RE: 0, NM: 0 };
  vis.forEach((it) => byT[it.t]++);
  $("shareBar").innerHTML = Object.keys(TYPES).filter((k) => byT[k]).map((k) =>
    `<span style="flex-grow:${byT[k]};background:${TYPES[k].color}" title="${TYPES[k].name}: ${byT[k]} (${Math.round(byT[k] / n * 100)}%)"></span>`).join("");

  const facet = (skip, key) => { const m = {}; state.items.forEach((it) => { if (matches(it, skip)) m[it[key]] = (m[it[key]] || 0) + 1; }); return m; };
  const ft = facet("t", "t"), fs = facet("s", "s"), fr = facet("ra", "cra");

  document.querySelectorAll("#subMedidores .sub").forEach((row) => {
    const k = row.dataset.t, on = state.types.has(k);
    row.classList.toggle("off", !on);
    row.querySelector("input").checked = on;
    row.querySelector("[data-n]").textContent = ft[k] || 0;
  });
  const sw = $("swMedidores");
  sw.checked = state.types.size > 0;
  sw.indeterminate = state.types.size > 0 && state.types.size < 3;
  $("cntMedidores").textContent = n;

  document.querySelectorAll("#dirChips .chip").forEach((b) => {
    b.setAttribute("aria-pressed", String(state.dirs.has(b.dataset.s)));
    b.querySelector("[data-n]").textContent = fs[b.dataset.s] || 0;
  });
  const maxRa = Math.max(1, ...Object.values(fr));
  document.querySelectorAll("#raList li").forEach((li) => {
    const cra = Number(li.dataset.cra), c = fr[cra] || 0, on = state.ras.has(cra);
    li.querySelector("input").checked = on;
    li.classList.toggle("off", !on);
    li.querySelector(".ra-n").textContent = c;
    li.querySelector(".ra-bar i").style.width = (c / maxRa * 100) + "%";
  });

  if (ds) {
    const vset = new Set(vis.map((it) => it.id));
    state.items.forEach((it) => { it.entity.show = vset.has(it.id); });
    viewer.scene.requestRender();
  }
  if (state.selected && !matches(state.byId.get(state.selected))) closeCard();

  state.listLimit = PAGE;
  renderList(vis);
}

function renderList(vis = visibleItems()) {
  $("listCount").textContent = vis.length;
  if (!vis.length) { $("results").innerHTML = `<li class="empty">Nenhum medidor com esses filtros. Ligue mais tipos em Camadas ou marque mais sentidos e RAs em Filtros.</li>`; return; }
  const rows = vis.slice(0, state.listLimit).map((it) => `
    <li><button type="button" data-id="${it.id}" ${it.id === state.selected ? 'aria-current="true"' : ""}>
      <span class="sw">${icoHTML(it.t)}</span>
      <span class="r-top"><span class="r-id">${it.id}</span><span class="r-ra">${esc(it.ra)}</span></span>
      <span class="r-addr">${esc(it.end)}</span>
    </button></li>`).join("");
  const more = vis.length > state.listLimit ? `<li><button type="button" class="more">Mostrar mais ${Math.min(PAGE, vis.length - state.listLimit)} de ${vis.length - state.listLimit} restantes</button></li>` : "";
  $("results").innerHTML = rows + more;
}

/* ================= seleção ================= */
function select(id, fly) {
  const it = state.byId.get(id); if (!it) return;
  if (state.selected && state.selected !== id) unmark(state.selected);
  state.selected = id;
  if (it.entity) {
    it.entity.billboard.image = state.icons[it.t].s;
    it.entity.billboard.width = it.entity.billboard.height = 40;
    it.entity.label.show = true;
    viewer.scene.requestRender();
  }
  $("cId").textContent = it.id;
  $("cType").innerHTML = `${icoHTML(it.t)}${TYPES[it.t].name}`;
  $("cAddr").textContent = it.end;
  $("cRa").textContent = `${String(it.cra).padStart(2, "0")} · ${it.ra}`;
  $("cDir").textContent = DIRS[it.s];
  $("cXY").textContent = `${it.lat.toFixed(6)}, ${it.lon.toFixed(6)}`;
  $("lSv").href = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${it.lat},${it.lon}`;
  $("lGm").href = `https://www.google.com/maps/search/?api=1&query=${it.lat},${it.lon}`;
  $("lGe").href = `https://earth.google.com/web/@${it.lat},${it.lon},1100a,450d,35y,0h,60t,0r`;
  fillCardWx(it);
  $("card").hidden = false;
  document.querySelectorAll("#results [data-id]").forEach((b) => (b.dataset.id === id ? b.setAttribute("aria-current", "true") : b.removeAttribute("aria-current")));
  state.lastOrbit = null;
  if (viewer) { stopOrbit(); placeMarkerFx(it, 0); }   // destaque imediato; ajusta a altura do chão no voo
  updateOrbitBtn();
  if (fly && viewer) flyToItem(it);
}

function unmark(id) {
  const it = state.byId.get(id);
  if (it && it.entity) {
    const C = Cesium;
    it.entity.position = C.Cartesian3.fromDegrees(it.lon, it.lat);       // volta para o chão
    it.entity.billboard.heightReference = C.HeightReference.CLAMP_TO_GROUND;
    it.entity.label.heightReference = C.HeightReference.CLAMP_TO_GROUND;
    it.entity.billboard.image = state.icons[it.t].n;
    it.entity.billboard.width = it.entity.billboard.height = 28;
    it.entity.label.show = false;
  }
  if (viewer) clearMarkerFx();
}

function closeCard() {
  if (viewer) stopOrbit();
  if (state.selected) unmark(state.selected);
  state.selected = null;
  $("card").hidden = true;
  document.querySelectorAll("#results [aria-current]").forEach((b) => b.removeAttribute("aria-current"));
  if (viewer) viewer.scene.requestRender();
}

/* ================= exportação ================= */
function exportCsv() {
  const vis = visibleItems();
  const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const head = ["ID EQUIP", "TIPO", "COD. RA", "RA", "ENDEREÇO", "SENTIDO", "LATITUDE", "LONGITUDE"];
  const lines = [head.join(";")].concat(vis.map((it) =>
    [it.id, TYPES[it.t].name, String(it.cra).padStart(2, "0"), it.ra, it.end, DIRS[it.s], it.lat, it.lon].map(q).join(";")));
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `medidores-velocidade-df-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`${vis.length} medidores exportados.`);
}

let toastT;
function toast(msg) {
  const el = $("toast"); el.textContent = msg; el.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (el.hidden = true), 5000);
}
