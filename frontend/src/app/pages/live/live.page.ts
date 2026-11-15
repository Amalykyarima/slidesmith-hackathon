import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, ElementRef, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Room, RoomEvent, Track, type RemoteTrack } from 'livekit-client';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../../core/api.service';
import { Adaptation, PupilDetail, SenService } from '../../core/sen';
import { Generation, LevelKey } from '../../core/models';
import { AgentRun } from '../../shared/agent-run';

type Mode = 'debrief' | 'build' | 'present';

interface Caption {
  id: string;
  who: 'avatar' | 'you';
  text: string;
}

interface Escalation {
  question: string;
  reason: string;
  at: Date;
  answered: boolean;
}

interface Result {
  key: number;
  kind: 'working' | 'adapted' | 'history' | 'record';
  title?: string;
  code?: string;
  id?: string;
  pupil_id?: string;
  adaptation?: Adaptation;
  pupil?: PupilDetail;
}

/** Text streams (lk.transcription) are installed on the full Room but not on its public type. */
interface TextStreams {
  registerTextStreamHandler(
    topic: string,
    cb: (reader: AsyncIterable<string> & { info: { id: string; attributes?: Record<string, string> } }, who: { identity: string }) => void,
  ): void;
}

/** SlideSmith Live: a Synthesia avatar that builds lessons by voice and presents them to the class. */
@Component({
  selector: 'app-live-page',
  imports: [FormsModule, RouterLink, AgentRun],
  template: `
    <h1>Your SEN assistant</h1>
    <p class="lead">
      Talk to Sam before and after a lesson. <strong>Prepare</strong>: adapt classwork for a pupil. <strong>What works</strong>: hear what's
      helped a pupil so far. <strong>Debrief</strong>: one minute after the lesson becomes a record to approve. For staff only: pupils are never on the call.
    </p>

    @if (configured() === false) {
      <div class="alert alert-warn" role="status">
        The live avatar isn't switched on for this server yet. It needs the LiveKit keys and <code>AVATAR_SECRET</code> in the backend,
        and the avatar worker running (see <code>avatar/README.md</code>).
      </div>
    }
    @if (error(); as m) {
      <div class="alert alert-error" role="alert">{{ m }}</div>
    }

    @if (!connected()) {
      <section class="card section">
        <div class="modes" role="radiogroup" aria-label="What should the avatar do?">
          <button type="button" role="radio" class="mode" [class.on]="mode() === 'debrief'" [attr.aria-checked]="mode() === 'debrief'" (click)="mode.set('debrief')">
            <strong>🗣️ SEN assistant</strong>
            <span class="muted small">Prepare, what works, and debrief, by voice.</span>
          </button>
        </div>
        <div class="stack opts">
          @if (mode() === 'debrief') {
            <p class="small muted">Refer to pupils by their code (for example "Y4-AB"), never by name. Safeguarding concerns go to your designated safeguarding lead, not here.
              New here? <a routerLink="/sen">Load the demo school</a> on the Pupils page first.</p>
          } @else if (mode() === 'build') {
            <label class="field">
              Usually for
              <select class="input" [ngModel]="level()" (ngModelChange)="level.set($event)">
                <option value="primary">Primary</option>
                <option value="secondary">Secondary</option>
                <option value="university">University / FE</option>
              </select>
            </label>
          } @else {
            <label class="field">
              Deck
              <select class="input" [ngModel]="deckId()" (ngModelChange)="deckId.set($event)">
                @for (g of decks(); track g.id) {
                  <option [value]="g.id">{{ g.title }} ({{ g.slides.length }} slides)</option>
                } @empty {
                  <option value="">No decks yet</option>
                }
              </select>
            </label>
            @if (!decks().length) {
              <p class="small muted">Make one on <a routerLink="/create">Create slides</a>, or build one by voice first.</p>
            }
            <label class="field">
              Class
              <select class="input" [ngModel]="level()" (ngModelChange)="level.set($event)">
                <option value="primary">Primary</option>
                <option value="secondary">Secondary</option>
                <option value="university">University / FE</option>
              </select>
            </label>
          }
          <div class="row">
            <button type="button" class="btn btn-primary btn-lg" [disabled]="connecting() || (mode() === 'present' && !deckId())" (click)="start()">
              @if (connecting()) {
                <span class="spinner"></span> Calling the avatar…
              } @else {
                Start
              }
            </button>
            <span class="small muted">Uses your microphone. The avatar takes up to a minute to join the first time.</span>
          </div>
        </div>
      </section>
    }

    @if (connected() || connecting()) {
      <div class="stage">
        <section class="card avatar-card">
          <div class="video" [class.waiting]="!avatarJoined()">
            <video #video autoplay playsinline></video>
            @if (!avatarJoined()) {
              <div class="video-wait"><span class="spinner"></span> Waiting for the avatar to join…</div>
            }
            <span class="live-chip">● Live · {{ live() === 'present' ? 'Presenting' : live() === 'debrief' ? (task() || 'SEN assistant') : 'Building' }}{{ activity() ? ' · ' + activity() : '' }}</span>
          </div>
          <div class="captions" aria-live="polite" aria-label="Captions">
            @for (c of captions(); track c.id) {
              <p [class]="'cap cap-' + c.who"><strong>{{ c.who === 'avatar' ? 'Sam' : 'You' }}:</strong> {{ c.text }}</p>
            } @empty {
              <p class="muted small">Captions appear here as you talk.</p>
            }
          </div>
          <div class="row controls">
            <button type="button" class="btn" (click)="toggleMic()">{{ micOn() ? '🎙️ Mute' : '🔇 Unmute' }}</button>
            @if (builtId() && live() === 'build') {
              <button type="button" class="btn btn-primary" (click)="send({ type: 'present' })">Present this deck</button>
            }
            <button type="button" class="btn danger" (click)="stop()">End session</button>
          </div>
        </section>

        <aside class="side">
          @if (escalations().length) {
            <section class="card section inbox">
              <h3>For you, from the class</h3>
              @for (e of escalations(); track e.at; let i = $index) {
                <div class="esc" [class.safe]="e.reason.startsWith('safeguarding')" [class.done]="e.answered">
                  <span class="small"><strong>{{ e.reason.startsWith('safeguarding') ? '⚠️ Safeguarding' : 'Question' }}</strong> · {{ e.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</span>
                  <p>{{ e.question }}</p>
                  @if (!e.answered && !e.reason.startsWith('safeguarding')) {
                    <div class="row">
                      <input class="input" #ans placeholder="Your answer, the avatar tells the class" (keydown.enter)="reply(i, ans.value); ans.value = ''" />
                      <button type="button" class="btn btn-sm" (click)="reply(i, ans.value); ans.value = ''">Send</button>
                    </div>
                  } @else if (!e.answered) {
                    <button type="button" class="btn btn-sm" (click)="markDone(i)">I've dealt with this</button>
                  }
                </div>
              }
            </section>
          }

          @if (live() === 'present' && previews().length) {
            <section class="card section">
              <h3>{{ deckTitle() }}</h3>
              <img class="current" [src]="previews()[slide() - 1]" [alt]="'Slide ' + slide()" />
              <div class="thumbs">
                @for (p of previews(); track p; let i = $index) {
                  <button type="button" [class.on]="slide() === i + 1" (click)="goto(i + 1)" [attr.aria-label]="'Go to slide ' + (i + 1)">
                    <img [src]="p" alt="" loading="lazy" />
                  </button>
                }
              </div>
            </section>
          }

          @if (live() === 'debrief') {
            @for (r of results(); track r.key) {
              <section class="card section rec">
                @switch (r.kind) {
                  @case ('working') {
                    <h3><span class="spinner"></span> {{ r.title }}</h3>
                  }
                  @case ('adapted') {
                    <span class="tag prep">Prepare · {{ r.code }}</span>
                    @if (r.adaptation; as a) {
                      <h3>{{ a.title }}</h3>
                      <p class="small"><strong>Objective:</strong> {{ a.objective }}</p>
                      <ol class="small">@for (i of a.instructions.slice(0, 4); track $index) { <li>{{ i.replace(stripNum, '') }}</li> }</ol>
                      <p class="small muted">Draft: check before use.</p>
                    }
                    <a class="btn btn-primary btn-sm" [routerLink]="['/adapt']" [queryParams]="{ result: r.id }" target="_blank">Open, print or make visual supports</a>
                  }
                  @case ('history') {
                    <span class="tag what">What works · {{ r.code }}</span>
                    <h3>What's worked for {{ r.code }}</h3>
                    @if (r.pupil; as p) {
                      <p class="small"><strong>Support in place:</strong> {{ p.provision.join(', ') || 'none recorded' }}</p>
                      @for (rec of approvedOf(p); track rec.id) {
                        <div class="small hist">
                          <strong>{{ rec.created_at.slice(0, 10) }}</strong> · {{ rec.record.do }}
                          @if (rec.record.plan.outcomes.length) { <br /><em>Aim: {{ rec.record.plan.outcomes[0] }}</em> }
                        </div>
                      } @empty { <p class="small muted">No approved records yet.</p> }
                    }
                    <p class="small muted">Sam answered from approved records only.</p>
                    <a class="btn btn-sm" [routerLink]="['/pupils', r.pupil_id]" target="_blank">Open {{ r.code }}'s page</a>
                  }
                  @case ('record') {
                    <span class="tag deb">Debrief · {{ r.code }}</span>
                    <h3>✅ Draft record for {{ r.code }} is ready</h3>
                    <p class="small muted">Check it, edit anything, and approve it. It isn't evidence until a member of staff approves it.</p>
                    <a class="btn btn-primary btn-sm" [routerLink]="['/pupils', r.pupil_id]" target="_blank">Review and approve</a>
                  }
                }
              </section>
            } @empty {
              <section class="card section">
                <h3>Try saying</h3>
                <ul class="small says">
                  <li><strong>Prepare:</strong> “I'm teaching equivalent fractions to Year 4 tomorrow. Can you adapt it for Y4-AB?”</li>
                  <li><strong>What works:</strong> “What's worked for Y4-AB so far?”</li>
                  <li><strong>Debrief:</strong> “Debrief for Y4-AB. We tried a Now/Next board in maths; he finished three of four tasks.”</li>
                </ul>
              </section>
            }
          }
          @if (runId(); as id) {
            <app-agent-run [runId]="id" (built)="builtId.set($event.run.generation_id)" />
          } @else if (live() === 'build') {
            <section class="card section">
              <h3>Try saying</h3>
              <ul class="small says">
                <li>“A Year 4 lesson on volcanoes, 8 slides, with SEN support.”</li>
                <li>“A first-year university lecture on supply and demand, 10 slides.”</li>
                <li>“How is it going?” · “Present it to the class.”</li>
              </ul>
            </section>
          }
        </aside>
      </div>
    }
  `,
  styles: `
    .modes { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .mode { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; text-align: left; cursor: pointer;
      padding: 14px 16px; border: 1.5px solid var(--border); border-radius: 12px; background: #fff; font: inherit; color: inherit; }
    .mode:hover { border-color: var(--primary); }
    .mode.on { border-color: var(--primary); background: var(--primary-soft); box-shadow: 0 0 0 1px var(--primary) inset; }
    @media (max-width: 640px) { .modes { grid-template-columns: 1fr; } }
    .opts { margin-top: 16px; max-width: 520px; }
    .stage { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 18px; align-items: start; }
    .avatar-card { overflow: hidden; }
    .video { position: relative; aspect-ratio: 16 / 10; background: #0f172a; }
    .video video { width: 100%; height: 100%; object-fit: cover; display: block; }
    .video-wait { position: absolute; inset: 0; display: grid; place-items: center; color: #cbd5e1; gap: 8px; }
    .live-chip { position: absolute; top: 12px; left: 12px; padding: 4px 10px; border-radius: 999px; background: rgba(15, 23, 42, 0.7); color: #fff;
      font-size: 12.5px; font-weight: 700; }
    .captions { height: 150px; overflow: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid var(--border); font-size: 15px; }
    .cap-you { color: var(--muted); }
    .controls { padding: 12px 16px; justify-content: flex-end; }
    .danger { color: var(--danger); }
    .side { display: flex; flex-direction: column; gap: 14px; }
    .current { width: 100%; border-radius: 8px; border: 1px solid var(--border); margin: 8px 0; }
    .thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr)); gap: 6px; }
    .thumbs button { padding: 0; border: 2px solid transparent; border-radius: 6px; background: none; cursor: pointer; }
    .thumbs button.on { border-color: var(--primary); }
    .thumbs img { width: 100%; display: block; border-radius: 4px; }
    .inbox { border-top: 4px solid #7c3aed; }
    .esc { padding: 10px 0; border-bottom: 1px dashed var(--border); display: flex; flex-direction: column; gap: 6px; }
    .esc.safe { background: #fef2f2; padding: 10px; border-radius: 8px; }
    .esc.done { opacity: 0.5; }
.rec { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
    .rec h3 { display: flex; gap: 8px; align-items: center; margin: 0; }
    .rec ol { margin: 0; padding-left: 18px; }
    .hist { border-left: 3px solid #fcd34d; padding: 4px 10px; }
    .tag { font-size: 11.5px; font-weight: 700; padding: 3px 9px; border-radius: 999px; }
    .prep { background: #e0f2fe; color: #075985; } .what { background: #fef3c7; color: #92400e; } .deb { background: #ede9fe; color: #5b21b6; }
    .says { padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
    @media (max-width: 900px) { .stage { grid-template-columns: 1fr; } }
  `,
})
export class LivePage {
  private readonly http = inject(HttpClient);
  private readonly video = viewChild<ElementRef<HTMLVideoElement>>('video');
  private room: Room | null = null;
  private audioEls: HTMLMediaElement[] = [];

  protected readonly configured = signal<boolean | null>(null);
  protected readonly mode = signal<Mode>('debrief');
  protected readonly results = signal<Result[]>([]);
  protected readonly task = signal('');
  protected readonly stripNum = /^\s*\d+[.)]\s*/;
  private readonly sen = inject(SenService);
  private seq = 0;

  protected approvedOf(p: PupilDetail) {
    return p.records.filter((r) => r.status === 'approved').slice(0, 2);
  }

  /** Newest first; a finished result replaces the "working" card it belongs to. */
  private push(r: Omit<Result, 'key'>): Result {
    const item = { ...r, key: ++this.seq } as Result;
    this.results.update((list) => [item, ...list.filter((x) => x.kind !== 'working')].slice(0, 6));
    return item;
  }
  protected readonly level = signal<LevelKey>('primary');
  protected readonly decks = signal<Generation[]>([]);
  protected readonly deckId = signal('');
  protected readonly connecting = signal(false);
  protected readonly connected = signal(false);
  protected readonly avatarJoined = signal(false);
  protected readonly micOn = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly captions = signal<Caption[]>([]);
  protected readonly escalations = signal<Escalation[]>([]);
  /** What the avatar is doing now (it can switch from build to present mid-session). */
  protected readonly live = signal<Mode>('build');
  protected readonly activity = signal('');
  protected readonly runId = signal<string | null>(null);
  protected readonly builtId = signal<string | null>(null);
  protected readonly previews = signal<string[]>([]);
  protected readonly deckTitle = signal('');
  protected readonly slide = signal(1);

  constructor() {
    inject(DestroyRef).onDestroy(() => void this.stop());
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.configured.set((await firstValueFrom(this.http.get<{ configured: boolean }>('/api/avatar'))).configured);
      const decks = await firstValueFrom(this.http.get<Generation[]>('/api/generations'));
      this.decks.set(decks);
      if (decks.length && !this.deckId()) this.deckId.set(decks[0].id);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected async start(): Promise<void> {
    this.error.set(null);
    this.connecting.set(true);
    this.captions.set([]);
    this.escalations.set([]);
    this.runId.set(null);
    this.builtId.set(null);
    this.results.set([]);
    this.task.set('');
    this.live.set(this.mode());
    try {
      const t = await firstValueFrom(
        this.http.post<{ url: string; token: string }>('/api/avatar/token', {
          mode: this.mode(),
          level: this.level(),
          generation_id: this.mode() === 'present' ? this.deckId() : undefined,
        }),
      );
      const room = new Room({ adaptiveStream: false, dynacast: true });
      this.room = room;
      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => this.attach(track));
      room.on(RoomEvent.DataReceived, (payload, _p, _k, topic) => {
        if (topic === 'slidesmith') this.onMessage(payload);
      });
      room.on(RoomEvent.Disconnected, () => this.reset());
      (room as unknown as TextStreams).registerTextStreamHandler?.('lk.transcription', (reader, who) => void this.caption(reader, who));
      await room.connect(t.url, t.token);
      await room.localParticipant.setMicrophoneEnabled(true);
      this.connected.set(true);
    } catch (err) {
      this.error.set(err instanceof HttpErrorResponse ? errorMessage(err)
        : `Couldn't reach the live avatar service (${err instanceof Error ? err.message : 'unknown error'}). Check your internet connection and LIVEKIT_URL.`);
      await this.stop();
    } finally {
      this.connecting.set(false);
    }
  }

  private attach(track: RemoteTrack): void {
    if (track.kind === Track.Kind.Video) {
      const el = this.video()?.nativeElement;
      if (el) track.attach(el);
      this.avatarJoined.set(true);
    } else if (track.kind === Track.Kind.Audio) {
      const el = track.attach();
      el.style.display = 'none';
      document.body.appendChild(el);
      this.audioEls.push(el);
    }
  }

  /** Live captions for both sides (also helps deaf pupils and anyone in a noisy room). */
  private async caption(
    reader: AsyncIterable<string> & { info: { id: string; attributes?: Record<string, string> } },
    who: { identity: string },
  ): Promise<void> {
    const mine = who.identity === this.room?.localParticipant.identity;
    const id = reader.info.attributes?.['lk.segment_id'] || reader.info.id;
    let text = '';
    for await (const chunk of reader) {
      text += chunk;
      const entry: Caption = { id, who: mine ? 'you' : 'avatar', text: text.trim() };
      this.captions.update((list) => {
        const i = list.findIndex((c) => c.id === id);
        const next = i >= 0 ? list.map((c, k) => (k === i ? entry : c)) : [...list, entry];
        return next.slice(-12);
      });
    }
  }

  private onMessage(payload: Uint8Array): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(new TextDecoder().decode(payload));
    } catch {
      return;
    }
    switch (msg['type']) {
      case 'mode':
        this.live.set(msg['mode'] === 'present' ? 'present' : msg['mode'] === 'debrief' ? 'debrief' : 'build');
        if (Array.isArray(msg['previews'])) this.previews.set(msg['previews'] as string[]);
        if (typeof msg['title'] === 'string') this.deckTitle.set(msg['title']);
        this.slide.set(1);
        break;
      case 'task':
        this.task.set(String(msg['task'] ?? ''));
        if (msg['working']) this.push({ kind: 'working', title: msg['task'] === 'Prepare' ? `Adapting classwork for ${msg['code']}…` : `Writing the record for ${msg['code']}…` });
        break;
      case 'adapted': {
        const item = this.push({ kind: 'adapted', code: String(msg['code']), id: String(msg['id']) });
        firstValueFrom(this.sen.adaptation(String(msg['id']))).then(
          (a) => this.results.update((list) => list.map((r) => (r.key === item.key ? { ...r, adaptation: a } : r))),
          () => undefined,
        );
        break;
      }
      case 'history': {
        const item = this.push({ kind: 'history', code: String(msg['code']), pupil_id: String(msg['pupil_id']) });
        firstValueFrom(this.sen.pupil(String(msg['pupil_id']))).then(
          (p) => this.results.update((list) => list.map((r) => (r.key === item.key ? { ...r, pupil: p } : r))),
          () => undefined,
        );
        break;
      }
      case 'record':
        this.push({ kind: 'record', code: String(msg['code']), pupil_id: String(msg['pupil_id']) });
        break;
      case 'run':
        this.runId.set(String(msg['run_id']));
        break;
      case 'built':
        this.builtId.set(String(msg['generation_id']));
        break;
      case 'slide':
        this.slide.set(Math.max(1, Number(msg['n']) || 1));
        break;
      case 'activity':
        this.activity.set({ present: '', questions: 'Questions', quiz: 'Quiz' }[String(msg['mode'])] ?? '');
        break;
      case 'escalation':
        this.escalations.update((list) => [
          { question: String(msg['question'] ?? ''), reason: String(msg['reason'] ?? ''), at: new Date(), answered: false },
          ...list,
        ]);
        break;
    }
  }

  protected async send(msg: Record<string, unknown>): Promise<void> {
    await this.room?.localParticipant.publishData(new TextEncoder().encode(JSON.stringify(msg)), { reliable: true, topic: 'slidesmith' });
  }

  protected goto(n: number): void {
    this.slide.set(n);
    void this.send({ type: 'goto', n });
  }

  protected reply(i: number, text: string): void {
    if (!text.trim()) return;
    void this.send({ type: 'teacher_reply', text: text.trim() });
    this.markDone(i);
  }

  protected markDone(i: number): void {
    this.escalations.update((list) => list.map((e, k) => (k === i ? { ...e, answered: true } : e)));
  }

  protected async toggleMic(): Promise<void> {
    const on = !this.micOn();
    await this.room?.localParticipant.setMicrophoneEnabled(on);
    this.micOn.set(on);
  }

  protected async stop(): Promise<void> {
    const room = this.room;
    this.room = null;
    if (room) await room.disconnect();
    this.reset();
  }

  private reset(): void {
    this.audioEls.forEach((el) => el.remove());
    this.audioEls = [];
    this.connected.set(false);
    this.avatarJoined.set(false);
    void this.load();
  }

}
