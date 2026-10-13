import * as d3 from 'd3';
import { SourceRun } from '../services/api.service';

interface Particle { id: number; stage: number; slot: number; }

/** Persistent SVG: polling updates destinations without replacing moving circles. */
export class DiscoveryFlow {
  private svg;
  private particleLayer;
  private observer: ResizeObserver;
  private timer?: d3.Timer;
  private run?: SourceRun;
  private signature = '';
  private width = 0;
  private height = 340;
  private replayUntil = 0;
  private readonly colors = ['#69b1c4', '#c99a40', '#2c966b', '#a9a7b4'];
  private readonly labels = ['Pages found', 'Profile check', 'Saved', 'Not imported'];

  constructor(private host: HTMLElement) {
    this.svg = d3.select(host).append('svg').attr('width', '100%').attr('height', '100%')
      .attr('role', 'img').attr('aria-label', 'Job pages moving through discovery, profile checking, and their final outcome');
    this.svg.append('g').attr('class', 'flow-zones');
    this.particleLayer = this.svg.append('g').attr('class', 'flow-particles');
    this.observer = new ResizeObserver(() => { if (this.run) this.update(this.run); });
    this.observer.observe(host);
  }

  update(run: SourceRun, replay = false): void {
    const changedRun = this.run?.id !== run.id;
    this.run = run;
    const running = ['queued', 'running'].includes(run.status);
    const direct = Math.max(0, run.discovered_count || 0);
    const saved = Math.max(0, run.imported_count + run.updated_count);
    const evaluation = [...(run.log || [])].reverse().find(event => event.level === 'evaluate');
    const candidates = (run.log || []).filter(event => event.level === 'candidate');
    const qualified = Math.max(saved, evaluation?.count ?? candidates.length);
    const evaluated = Boolean(evaluation) || !running;
    const checking = (run.log || []).some(event => event.level === 'evaluating');
    // Cumulative counters are above the graphic; particles show current destinations.
    const total = Math.max(direct, qualified, saved);
    const pending = evaluated ? Math.max(0, qualified - saved - run.error_count) : total;
    const outcomes = evaluated
      ? [0, pending, saved, Math.max(0, total - saved - pending)]
      : checking ? [0, total, 0, 0] : [total, 0, 0, 0];
    const width = Math.max(280, this.host.clientWidth);
    const height = width < 620 ? 440 : 340;
    const signature = JSON.stringify([run.id, run.status, outcomes, width, height]);
    if (signature === this.signature && !replay) return;
    const resized = width !== this.width || height !== this.height;
    this.signature = signature;
    this.width = width;
    this.height = height;
    this.host.style.height = `${height}px`;
    this.host.dataset['runId'] = String(run.id);
    this.host.dataset['totalPages'] = String(total);
    this.host.dataset['running'] = String(running);
    this.svg.attr('viewBox', `0 0 ${width} ${height}`);
    this.drawZones(outcomes);
    if (changedRun || replay) {
      this.particleLayer.selectAll('*').interrupt('travel').remove();
      this.replayUntil = 0;
    }
    // Bound rendering for large historical runs, preserving every non-empty outcome.
    const budget = Math.min(total, 120);
    const counts = outcomes.map(count => count ? Math.max(1, Math.floor(count / Math.max(total, 1) * budget)) : 0);
    while (d3.sum(counts) < budget) counts[outcomes.indexOf(Math.max(...outcomes))]++;
    while (d3.sum(counts) > budget) counts[counts.indexOf(Math.max(...counts))]--;
    const particles: Particle[] = [];
    // Saved first gives these particles stable IDs while results accumulate.
    for (const stage of [2, 1, 3, 0]) {
      for (let slot = 0; slot < counts[stage]; slot++) particles.push({id: particles.length, stage, slot});
    }
    this.host.dataset['sampled'] = String(total > 120);
    const oldStages = new Map<number, number>();
    this.particleLayer.selectAll<SVGGElement, Particle>('g.particle').each(d => oldStages.set(d.id, d.stage));
    const groups = this.particleLayer.selectAll<SVGGElement, Particle>('g.particle')
      .data(particles, d => d.id).join(
        enter => {
          const group = enter.append('g').attr('class', 'particle').attr('data-page-id', d => d.id)
            .attr('transform', d => this.at(0, d.id, budget, true));
          group.append('circle').attr('r', 7).attr('fill', this.colors[0]).attr('stroke', 'white').attr('stroke-width', 2);
          group.append('title');
          return group;
        },
        update => update,
        exit => exit.interrupt('travel').remove(),
      );
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    groups.attr('data-destination', d => this.labels[d.stage]);
    groups.select('title').text(d => `Page ${d.id + 1} · ${this.labels[d.stage]}${total > 120 ? ' (representative sample)' : ''}`);
    groups.each((d, index, nodes) => {
      if (oldStages.get(d.id) === d.stage && !replay && !changedRun && !resized) return;
      const group = d3.select(nodes[index]).interrupt('travel');
      const destination = this.at(d.stage, d.slot, counts[d.stage]);
      if (reduced) {
        group.attr('transform', destination).attr('data-stage', d.stage);
        group.select('circle').attr('fill', this.colors[d.stage]);
        return;
      }
      const fresh = !oldStages.has(d.id) || changedRun || replay;
      const delay = fresh ? Math.min(index * 22, 1300) : 0;
      let movement = group.transition('travel').delay(delay).duration(fresh ? 750 : 0).ease(d3.easeCubicInOut);
      if (fresh) movement = movement.attr('transform', this.at(0, d.id, budget));
      if (d.stage !== 0) {
        movement = movement.transition().duration(1450).attr('transform', this.at(1, d.id, budget));
        movement.on('start.check', () => {
          group.attr('data-stage', 1);
          group.select('circle').attr('fill', this.colors[1]);
        });
      }
      movement.transition().duration(1250).attr('transform', destination).on('start.destination', () => {
        group.select('circle').attr('fill', this.colors[d.stage]);
      }).on('end', () => group.attr('data-stage', d.stage));
      this.replayUntil = Math.max(this.replayUntil, performance.now() + delay + 3600);
    });
    this.startMotion(running, reduced);
  }

  private zone(stage: number): { x: number; y: number; width: number; height: number } {
    const compact = this.width < 620;
    const columns = compact ? 2 : 4;
    return {x: (stage % columns) * this.width / columns + 6, y: Math.floor(stage / columns) * (compact ? this.height / 2 : this.height) + 6,
      width: this.width / columns - 12, height: (compact ? this.height / 2 : this.height) - 12};
  }

  private at(stage: number, slot: number, count: number, entry = false): string {
    const box = this.zone(stage);
    const cols = Math.max(1, Math.min(Math.ceil(Math.sqrt(count || 1)), Math.floor((box.width - 32) / 18)));
    const rows = Math.ceil(Math.max(count, 1) / cols);
    const spacing = Math.min(24, (box.height - 125) / Math.max(rows, 1));
    const x = entry ? box.x + 14 : box.x + box.width / 2 + ((slot % cols) - (cols - 1) / 2) * 19;
    const y = box.y + 106 + Math.floor(slot / cols) * spacing;
    return `translate(${x},${y})`;
  }

  private drawZones(counts: number[]): void {
    const zones = this.svg.select('.flow-zones').selectAll<SVGGElement, string>('g').data(this.labels).join(enter => {
      const group = enter.append('g');
      group.append('rect'); group.append('text').attr('class', 'zone-title'); group.append('text').attr('class', 'zone-count');
      return group;
    });
    zones.each((title, i, nodes) => {
      const box = this.zone(i); const group = d3.select(nodes[i]);
      group.select('rect').attr('x', box.x).attr('y', box.y).attr('width', box.width).attr('height', box.height)
        .attr('rx', 14).attr('fill', ['#f0f8fb', '#fff9eb', '#ecf8f1', '#f4f3f7'][i]).attr('stroke', '#dfe8e4');
      group.select('.zone-title').attr('x', box.x + 16).attr('y', box.y + 27).attr('font-size', 12).attr('font-weight', 600).attr('fill', '#42564b').text(title);
      group.select('.zone-count').attr('x', box.x + 16).attr('y', box.y + 59).attr('font-size', 24).attr('font-weight', 700).attr('fill', this.colors[i]).text(counts[i]);
    });
  }

  private startMotion(running: boolean, reduced: boolean): void {
    this.timer?.stop();
    if (reduced) { this.host.dataset['animating'] = 'false'; return; }
    this.host.dataset['animating'] = 'true';
    this.timer = d3.timer(elapsed => {
      this.particleLayer.selectAll<SVGCircleElement, Particle>('circle').attr('cy', d => Math.sin(elapsed / 650 + d.id * .7) * 3);
      if (!running && performance.now() >= this.replayUntil) {
        this.timer?.stop();
        this.host.dataset['animating'] = 'false';
        this.particleLayer.selectAll('circle').attr('cy', 0);
      }
    });
  }

  destroy(): void {
    this.observer.disconnect(); this.timer?.stop();
    this.particleLayer.selectAll('*').interrupt('travel'); this.svg.remove();
  }
}
