const SERIES = [
  { key: "Ux", color: "#4cc9f0", label: "Ux" },
  { key: "Uy", color: "#7bdcb5", label: "Uy" },
  { key: "p", color: "#f4a261", label: "p" },
  { key: "continuity", color: "#b39ddb", label: "continuidad" }
];

export class ResidualChart {
  constructor(canvas, emptyEl) {
    this.canvas = canvas;
    this.empty = emptyEl;
    this.ctx = canvas.getContext("2d");
    this.data = [];
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.resize();
    const ro = new ResizeObserver(() => {
      this.resize();
      this.draw();
    });
    ro.observe(canvas.parentElement);
    window.addEventListener("resize", () => {
      this.resize();
      this.draw();
    });
  }

  resize() {
    const parent = this.canvas.parentElement;
    const rect = parent.getBoundingClientRect();
    const w = Math.max(10, rect.width - 28);
    const h = Math.max(10, rect.height - 18);
    this.w = w;
    this.h = h;
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  }

  setData(series) {
    this.data = Array.isArray(series) ? series.filter((p) => p && Number.isFinite(Number(p.time))) : [];
    this.empty.classList.toggle("is-hidden", this.data.length > 1);
    this.draw();
  }

  draw() {
    const ctx = this.ctx;
    if (!ctx) return;
    const w = this.w;
    const h = this.h;
    ctx.clearRect(0, 0, w, h);
    if (!this.data.length) return;

    const pad = { left: 42, right: 12, top: 12, bottom: 20 };
    const plotW = Math.max(10, w - pad.left - pad.right);
    const plotH = Math.max(10, h - pad.top - pad.bottom);
    const times = this.data.map((p) => Number(p.time));
    const xmin = Math.min(...times);
    const xmax = Math.max(...times);
    const xspan = Math.max(1e-9, xmax - xmin);

    const values = [];
    this.data.forEach((p) => {
      SERIES.forEach((s) => {
        const v = Number(p[s.key]);
        if (Number.isFinite(v) && v > 0) values.push(v);
      });
    });
    if (!values.length) return;
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const lo = Math.max(1e-12, Math.min(minV, maxV / 10 || minV));
    const hi = Math.max(1e-1, maxV);
    const logLo = Math.floor(Math.log10(lo));
    const logHi = Math.ceil(Math.log10(hi));
    const span = Math.max(1, logHi - logLo);

    const xOf = (t) => pad.left + ((t - xmin) / xspan) * plotW;
    const yOf = (v) => {
      const lv = Math.log10(Math.max(lo, Math.min(hi, v)));
      return pad.top + plotH - ((lv - logLo) / span) * plotH;
    };

    ctx.save();
    ctx.strokeStyle = "rgba(148,163,184,.10)";
    ctx.lineWidth = 1;
    ctx.font = "8px 'Cascadia Code', monospace";
    ctx.fillStyle = "rgba(148,163,184,.6)";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= span; i += span > 8 ? 2 : 1) {
      const lv = logHi - i;
      const y = pad.top + (i / span) * plotH;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
      const label = lv === 0 ? "1" : `1e${lv}`;
      ctx.fillText(label, pad.left - 6, y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const xTicks = 5;
    for (let i = 0; i <= xTicks; i++) {
      const t = xmin + (i / xTicks) * xspan;
      const x = xOf(t);
      ctx.beginPath();
      ctx.strokeStyle = "rgba(148,163,184,.055)";
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + plotH);
      ctx.stroke();
      ctx.fillStyle = "rgba(148,163,184,.55)";
      ctx.fillText(this._fmt(t), x, pad.top + plotH + 6);
    }

    SERIES.forEach((s) => {
      const points = this.data
        .map((p) => [Number(p.time), Number(p[s.key])])
        .filter(([, v]) => Number.isFinite(v) && v > 0);
      if (points.length < 2) return;
      ctx.beginPath();
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.35;
      ctx.lineJoin = "round";
      points.forEach(([t, v], i) => {
        const x = xOf(t);
        const y = yOf(v);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      const [lt, lv] = points[points.length - 1];
      ctx.beginPath();
      ctx.arc(xOf(lt), yOf(lv), 2, 0, Math.PI * 2);
      ctx.fillStyle = s.color;
      ctx.fill();
    });

    // Axes
    ctx.strokeStyle = "rgba(148,163,184,.22)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top);
    ctx.lineTo(pad.left, pad.top + plotH);
    ctx.lineTo(w - pad.right, pad.top + plotH);
    ctx.stroke();
    ctx.restore();
  }

  _fmt(v) {
    if (Math.abs(v) >= 1000) return v.toExponential(1);
    if (Math.abs(v) >= 1) return v.toFixed(2).replace(/\.00$/, "");
    return v.toPrecision(2);
  }
}
