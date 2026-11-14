import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { BuildRequest, GenerateRequest, Generation, Health, Level, Run, RunSlide, ShapeEdit, SlideScene, SlideStyle, Supports, UploadedImage } from './models';

/** All backend calls live here. Paths are relative; `proxy.conf.json` forwards them to FastAPI in dev. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  health(): Observable<Health> {
    return this.http.get<Health>('/api/health');
  }

  listStyles(): Observable<SlideStyle[]> {
    return this.http.get<SlideStyle[]>('/api/styles');
  }

  uploadStyle(file: File, name = ''): Observable<SlideStyle> {
    const body = new FormData();
    body.append('file', file);
    if (name) body.append('name', name);
    return this.http.post<SlideStyle>('/api/styles', body);
  }

  renameStyle(id: string, name: string): Observable<SlideStyle> {
    return this.http.patch<SlideStyle>(`/api/styles/${id}`, { name });
  }

  /** Which of her sample slides SlideSmith must never copy (1-based slide numbers). */
  setExcludedSlides(id: string, excluded: number[]): Observable<SlideStyle> {
    return this.http.patch<SlideStyle>(`/api/styles/${id}`, { excluded });
  }

  deleteStyle(id: string): Observable<void> {
    return this.http.delete<void>(`/api/styles/${id}`);
  }

  uploadImage(file: File): Observable<UploadedImage> {
    const body = new FormData();
    body.append('file', file);
    return this.http.post<UploadedImage>('/api/images', body);
  }

  deleteImage(id: string): Observable<void> {
    return this.http.delete<void>(`/api/images/${id}`);
  }

  generate(request: GenerateRequest): Observable<Generation> {
    return this.http.post<Generation>('/api/generate', request);
  }

  /** Finished content, built word for word without the AI. */
  build(request: BuildRequest): Observable<Generation> {
    return this.http.post<Generation>('/api/build', request);
  }

  /** A slide as movable pieces for the on-slide editor (number is 1-based). */
  slideScene(genId: string, number: number): Observable<SlideScene> {
    return this.http.get<SlideScene>(`/api/generations/${genId}/slides/${number}`);
  }

  slideBackground(genId: string, number: number): Observable<{ background: string | null }> {
    return this.http.get<{ background: string | null }>(`/api/generations/${genId}/slides/${number}/background`);
  }

  saveSlide(genId: string, number: number, shapes: ShapeEdit[]): Observable<Generation> {
    return this.http.post<Generation>(`/api/generations/${genId}/slides/${number}`, { shapes });
  }

  getGeneration(id: string): Observable<Generation> {
    return this.http.get<Generation>(`/api/generations/${id}`);
  }

  levels(): Observable<Level[]> {
    return this.http.get<Level[]>('/api/levels');
  }

  /** Start the agent team (Orchestrator, Planner, SEN Adapter, Reviewer). Watch with runEvents(). */
  startRun(request: GenerateRequest): Observable<Run> {
    return this.http.post<Run>('/api/runs', request);
  }

  getRun(id: string): Observable<Run> {
    return this.http.get<Run>(`/api/runs/${id}`);
  }

  /** Human-in-the-loop: the teacher's edits and the flags she accepted. Builds the deck. */
  approveRun(id: string, slides: Partial<RunSlide>[], accepted: number[]): Observable<{ run: Run; generation: Generation }> {
    return this.http.post<{ run: Run; generation: Generation }>(`/api/runs/${id}/approve`, { slides, accepted });
  }

  /** Visual supports straight from a topic (no deck). */
  supports(topic: string, details: string, level: string): Observable<Supports> {
    return this.http.post<Supports>('/api/supports', { topic, details, level });
  }

  searchPictos(q: string): Observable<{ id: string; name: string; url: string }[]> {
    return this.http.get<{ id: string; name: string; url: string }[]>('/api/pictos/search', { params: { q } });
  }

  redrawPreviews(id: string): Observable<Generation> {
    return this.http.post<Generation>(`/api/generations/${id}/previews`, {});
  }
}

/** Turns any HTTP failure into a sentence a teacher can act on. */
export function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) return 'Cannot reach the server. Is the backend running on port 8000?';
    const detail = err.error?.detail;
    if (typeof detail === 'string') return detail;
    if (err.status === 422) return 'Some of the details look wrong. Please check the form and try again.';
    return `Something went wrong (${err.status}). Please try again.`;
  }
  return 'Something went wrong. Please try again.';
}
