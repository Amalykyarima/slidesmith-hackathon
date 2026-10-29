import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom, interval } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { SlideStyle } from '../../core/models';
import { BusyOverlay } from '../../shared/busy-overlay';
import { Lightbox } from '../../shared/lightbox';

@Component({
  selector: 'app-styles-page',
  imports: [RouterLink, BusyOverlay, Lightbox],
  templateUrl: './styles.page.html',
  styleUrl: './styles.page.css',
})
export class StylesPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  protected readonly styles = signal<SlideStyle[]>([]);
  protected readonly loading = signal(true);
  protected readonly uploading = signal<string[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly dragOver = signal(false);
  protected readonly editingId = signal<string | null>(null);
  /** Style whose sample slides are open full-size, or null. */
  protected readonly viewing = signal<SlideStyle | null>(null);

  constructor() {
    void this.refresh();
    // While LibreOffice is rendering thumbnails in the background, keep checking.
    interval(2500)
      .pipe(takeUntilDestroyed(inject(DestroyRef)))
      .subscribe(() => {
        if (this.styles().some((s) => s.preview_status === 'pending')) void this.refresh(false);
      });
  }

  private async refresh(showError = true): Promise<void> {
    try {
      this.styles.set(await firstValueFrom(this.api.listStyles()));
    } catch (err) {
      if (showError) this.error.set(errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  protected onPick(event: Event): void {
    const input = event.target as HTMLInputElement;
    void this.upload(Array.from(input.files ?? []));
    input.value = '';
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    void this.upload(Array.from(event.dataTransfer?.files ?? []));
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  private async upload(files: File[]): Promise<void> {
    this.error.set(null);
    for (const file of files) {
      if (!file.name.toLowerCase().endsWith('.pptx')) {
        this.error.set(`"${file.name}" is not a .pptx file. In PowerPoint use File → Save As → PowerPoint Presentation (.pptx).`);
        continue;
      }
      this.uploading.update((names) => [...names, file.name]);
      try {
        const created = await firstValueFrom(this.api.uploadStyle(file));
        this.styles.update((list) => [created, ...list]);
        if (files.length === 1) {
          // One new template: go straight to cooking a lesson with it.
          void this.router.navigate(['/create'], { queryParams: { style: created.id, cook: 1 } });
        }
      } catch (err) {
        this.error.set(errorMessage(err));
      } finally {
        this.uploading.update((names) => names.filter((n) => n !== file.name));
      }
    }
  }

  protected async commitRename(style: SlideStyle, value: string): Promise<void> {
    this.editingId.set(null);
    const name = value.trim();
    if (!name || name === style.name) return;
    try {
      const updated = await firstValueFrom(this.api.renameStyle(style.id, name));
      this.styles.update((list) => list.map((s) => (s.id === updated.id ? updated : s)));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected async remove(style: SlideStyle): Promise<void> {
    if (!confirm(`Remove "${style.name}"? New slides will no longer use this style.`)) return;
    try {
      await firstValueFrom(this.api.deleteStyle(style.id));
      this.styles.update((list) => list.filter((s) => s.id !== style.id));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected gradient(style: SlideStyle): string {
    const [a = '#0f766e', b = a] = style.profile.palette;
    return `linear-gradient(135deg, #${a.replace('#', '')}, #${b.replace('#', '')})`;
  }

  protected ratio(style: SlideStyle): string {
    const [w, h] = style.profile.slide_size_in;
    return `${w} / ${h}`;
  }

  protected kinds(style: SlideStyle): string[] {
    return Object.entries(style.profile.kinds).map(([kind, n]) => `${n} ${kind}`);
  }

  protected hex(color: string): string {
    return `#${color.replace('#', '')}`;
  }

  protected sampleCaptions(style: SlideStyle): string[] {
    return style.previews.map((_, i) => `${style.name} · sample ${i + 1}`);
  }
}
