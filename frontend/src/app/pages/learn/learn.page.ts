import { HttpClient } from '@angular/common/http';
import { Component, DestroyRef, ElementRef, computed, inject, input, signal, viewChild } from '@angular/core';
import { Room, RoomEvent, Track, type RemoteTrack } from 'livekit-client';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../../core/api.service';
import { DayPlan, SenService } from '../../core/sen';

interface TextStreams {
  registerTextStreamHandler(
    topic: string,
    cb: (reader: AsyncIterable<string> & { info: { id: string; attributes?: Record<string, string> } }, who: { identity: string }) => void,
  ): void;
}

const AVATARS = [
  { key: 'mei', name: 'Mei', emoji: '👩🏻' },
  { key: 'jenny', name: 'Jenny', emoji: '👩🏼' },
  { key: 'kenji', name: 'Kenji', emoji: '👨🏻' },
];

/** The pupil's day: their chosen avatar explains each lesson and shows it step by step. */
@Component({
  selector: 'app-learn-page',
  template: `
    @let d = day();
    <div class="learn">
      @if (error(); as m) { <div class="alert alert-error" role="alert">{{ m }}</div> }

      @if (!connected() && !connecting()) {
        <section class="card hello">
          <h1>Good morning{{ d ? ', ' + d.code : '' }}! 👋</h1>
          <p class="big">Who would you like to learn with today?</p>
          <div class="faces">
            @for (a of avatars; track a.key) {
              <button type="button" class="face" [class.on]="avatar() === a.key" (click)="avatar.set(a.key)">
                <span class="emoji">{{ a.emoji }}</span><span>{{ a.name }}</span>
              </button>
            }
          </div>
          <button type="button" class="btn btn-primary btn-lg go" [disabled]="!d" (click)="start()">Let's start</button>
          @if (d && !d.periods.length) { <p class="small muted">Your teacher hasn't set today's lessons yet.</p> }
        </section>
      }

      @if (connected() || connecting()) {
        <div class="stage">
          <section class="card av">
            <div class="video" [class.waiting]="!joined()">
              <video #video autoplay playsinline></video>
              @if (!joined()) { <div class="wait"><span class="spinner"></span> {{ name() }} is coming…</div> }
            </div>
            <div class="caps" aria-live="polite">
              @for (c of captions(); track c.id) {
                <p [class.me]="c.me"><strong>{{ c.me ? 'You' : name() }}:</strong> {{ c.text }}</p>
              }
            </div>
            <div class="row ctl">
              <button type="button" class="btn" (click)="toggleMic()">{{ mic() ? '🎙️ Mute' : '🔇 Unmute' }}</button>
              <button type="button" class="btn" (click)="stop()">Finish</button>
            </div>
            @if (helpSent(); as h) {
              <div class="helped">{{ h === 'safeguarding' ? '💛 A grown-up is coming to help you.' : '🙋 Your teacher has been told. They are coming.' }}</div>
            }
          </section>

          @if (d) {
            <section class="card plan">
              <ol class="periods">
                @for (p of d.periods; track p.n) {
                  <li [class.now]="p.n === current()" [class.done]="p.n < current()" (click)="current.set(p.n)">
                    <span class="pn">{{ p.time || 'P' + p.n }}</span>
                    <strong>{{ p.subject }}</strong>
                  </li>
                }
              </ol>
              @if (period(); as p) {
                <h2>{{ p.subject }}</h2>
                @if (p.breakdown; as b) {
                  @for (t of b.task_steps; track $index) {
                    <ol class="steps">
                      @for (s of t.steps; track $index; let i = $index) {
                        <li [class.ticked]="ticked().has(p.n + ':' + i)" (click)="tick(p.n + ':' + i)">
                          <span class="num">{{ i + 1 }}</span>
                          @if (s.picto_url) { <img [src]="s.picto_url" [alt]="s.picto_name || ''" /> } @else { <span class="noimg"></span> }
                          <span class="txt">{{ s.text }}</span>
                          <span class="box">{{ ticked().has(p.n + ':' + i) ? '✓' : '' }}</span>
                        </li>
                      }
                    </ol>
                  }
                  @if (b.key_words.length) {
                    <div class="words">
                      @for (k of b.key_words.slice(0, 6); track k.word) {
                        <div class="word">@if (k.picto_url) { <img [src]="k.picto_url" alt="" /> }<strong>{{ k.word }}</strong><span>{{ k.meaning }}</span></div>
                      }
                    </div>
                  }
                } @else {
                  <p class="big">{{ p.learn }}</p>
                }
                @if (p.video_url) {
                  <a class="btn video-btn" [class.glow]="videoFor() === p.n" [href]="p.video_url" target="_blank" rel="noopener">▶ Watch: {{ p.video_title || 'the video' }}</a>
                }
              }
              <p class="credit">Symbols: OpenMoji, CC BY-SA 4.0</p>
            </section>
          }
        </div>
      }
    </div>
  `,
  styles: `
    .learn { font-family: Arial, Helvetica, sans-serif; letter-spacing: 0.02em; }
    .hello { max-width: 640px; margin: 20px auto; padding: 32px; text-align: center; display: flex; flex-direction: column; gap: 18px; align-items: center; }
    .hello h1 { font-size: 34px; } .big { font-size: 20px; }
    .faces { display: flex; gap: 14px; flex-wrap: wrap; justify-content: center; }
    .face { display: flex; flex-direction: column; align-items: center; gap: 6px; width: 120px; padding: 16px; border: 3px solid var(--border);
      border-radius: 18px; background: #fff; font-size: 18px; font-weight: 700; cursor: pointer; }
    .face .emoji { font-size: 54px; } .face.on { border-color: var(--primary); background: var(--primary-soft); }
    .go { font-size: 20px; padding: 14px 34px; }
    .stage { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 18px; align-items: start; }
    .av { overflow: hidden; position: relative; }
    .video { aspect-ratio: 4 / 3; background: #0f172a; position: relative; }
    .video video { width: 100%; height: 100%; object-fit: cover; display: block; }
    .wait { position: absolute; inset: 0; display: grid; place-items: center; color: #e2e8f0; font-size: 18px; }
    .caps { height: 130px; overflow: auto; padding: 10px 16px; font-size: 17px; display: flex; flex-direction: column; gap: 4px; }
    .caps p { margin: 0; } .caps .me { color: var(--muted); }
    .ctl { padding: 10px 16px; justify-content: flex-end; border-top: 1px solid var(--border); }
    .helped { margin: 0 16px 16px; padding: 12px; border-radius: 12px; background: #fef3c7; font-size: 17px; font-weight: 700; text-align: center; }
    .plan { padding: 20px; display: flex; flex-direction: column; gap: 14px; background: #fdf6e3; }
    .periods { list-style: none; margin: 0; padding: 0; display: flex; gap: 8px; flex-wrap: wrap; }
    .periods li { padding: 8px 14px; border-radius: 12px; border: 2.5px solid #cbd5e1; background: #fff; cursor: pointer; display: flex; gap: 8px; align-items: center; font-size: 16px; }
    .periods li.now { border-color: #16a34a; background: #f0fdf4; } .periods li.done { opacity: 0.45; }
    .pn { font-size: 13px; color: var(--muted); }
    .plan h2 { font-size: 28px; margin: 0; }
    .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
    .steps li { display: grid; grid-template-columns: 36px 56px 1fr 36px; gap: 12px; align-items: center; padding: 10px 14px; background: #fff;
      border: 2.5px solid #cbd5e1; border-radius: 14px; font-size: 19px; font-weight: 600; cursor: pointer; }
    .steps li.ticked { border-color: #16a34a; background: #f0fdf4; }
    .num { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: var(--primary); color: #fff; font-weight: 800; }
    .steps img, .noimg { width: 52px; height: 52px; }
    .box { display: grid; place-items: center; width: 32px; height: 32px; border: 3px solid #94a3b8; border-radius: 8px; color: #16a34a; font-weight: 900; font-size: 20px; }
    .words { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
    .word { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 4px; padding: 10px; background: #fff; border-radius: 12px; border: 2px solid #cbd5e1; font-size: 14px; }
    .word img { width: 52px; height: 52px; } .word strong { font-size: 17px; }
    .video-btn { align-self: flex-start; font-size: 18px; padding: 12px 20px; }
    .glow { box-shadow: 0 0 0 4px #fde047; background: #fef9c3; }
    .credit { font-size: 11px; color: #64748b; margin: 0; }
    @media (max-width: 900px) { .stage { grid-template-columns: 1fr; } }
  `,
})
export class LearnPage {
  private readonly sen = inject(SenService);
  private readonly http = inject(HttpClient);
  readonly id = input.required<string>();
  private readonly video = viewChild<ElementRef<HTMLVideoElement>>('video');
  private room: Room | null = null;
  private audio: HTMLMediaElement[] = [];

  protected readonly avatars = AVATARS;
  protected readonly avatar = signal('mei');
  protected readonly day = signal<DayPlan | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly connecting = signal(false);
  protected readonly connected = signal(false);
  protected readonly joined = signal(false);
  protected readonly mic = signal(true);
  protected readonly current = signal(1);
  protected readonly videoFor = signal(0);
  protected readonly helpSent = signal<string | null>(null);
  protected readonly ticked = signal(new Set<string>());
  protected readonly captions = signal<{ id: string; me: boolean; text: string }[]>([]);
  protected readonly name = computed(() => AVATARS.find((a) => a.key === this.avatar())?.name ?? 'Sam');
  protected readonly period = computed(() => this.day()?.periods.find((p) => p.n === this.current()) ?? null);

  constructor() {
    inject(DestroyRef).onDestroy(() => void this.stop());
  }

  async ngOnInit(): Promise<void> {
    try {
      this.day.set(await firstValueFrom(this.sen.day(this.id())));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected tick(k: string): void {
    const next = new Set(this.ticked());
    if (next.has(k)) next.delete(k);
    else next.add(k);
    this.ticked.set(next);
  }

  protected async start(): Promise<void> {
    this.error.set(null);
    this.connecting.set(true);
    try {
      const t = await firstValueFrom(
        this.http.post<{ url: string; token: string }>('/api/avatar/token', { mode: 'pupil', pupil_id: this.id(), avatar: this.avatar() }),
      );
      const room = new Room({ adaptiveStream: false, dynacast: true });
      this.room = room;
      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Video) {
          const el = this.video()?.nativeElement;
          if (el) track.attach(el);
          this.joined.set(true);
        } else if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          el.style.display = 'none';
          document.body.appendChild(el);
          this.audio.push(el);
        }
      });
      room.on(RoomEvent.DataReceived, (payload, _p, _k, topic) => {
        if (topic !== 'slidesmith') return;
        try {
          const msg = JSON.parse(new TextDecoder().decode(payload));
          if (msg.type === 'period') this.current.set(Number(msg.n) || 1);
          if (msg.type === 'video') {
            this.current.set(Number(msg.n) || 1);
            this.videoFor.set(Number(msg.n) || 0);
          }
          if (msg.type === 'help_sent') this.helpSent.set(String(msg.kind));
        } catch {
          /* ignore */
        }
      });
      room.on(RoomEvent.Disconnected, () => this.reset());
      (room as unknown as TextStreams).registerTextStreamHandler?.('lk.transcription', async (reader, who) => {
        const me = who.identity === room.localParticipant.identity;
        const id = reader.info.attributes?.['lk.segment_id'] || reader.info.id;
        let text = '';
        for await (const chunk of reader) {
          text += chunk;
          const entry = { id, me, text: text.trim() };
          this.captions.update((list) => {
            const i = list.findIndex((c) => c.id === id);
            return (i >= 0 ? list.map((c, k) => (k === i ? entry : c)) : [...list, entry]).slice(-8);
          });
        }
      });
      await room.connect(t.url, t.token);
      await room.localParticipant.setMicrophoneEnabled(true);
      this.connected.set(true);
    } catch (err) {
      this.error.set(errorMessage(err));
      await this.stop();
    } finally {
      this.connecting.set(false);
    }
  }

  protected async toggleMic(): Promise<void> {
    const on = !this.mic();
    await this.room?.localParticipant.setMicrophoneEnabled(on);
    this.mic.set(on);
  }

  protected async stop(): Promise<void> {
    const room = this.room;
    this.room = null;
    if (room) await room.disconnect();
    this.reset();
  }

  private reset(): void {
    this.audio.forEach((el) => el.remove());
    this.audio = [];
    this.connected.set(false);
    this.joined.set(false);
  }
}
