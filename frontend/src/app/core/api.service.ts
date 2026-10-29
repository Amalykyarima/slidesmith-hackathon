import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { BuildRequest, Draft, GenerateRequest, Generation, Health, SlideStyle, StyleLayouts, UploadedImage } from './models';

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

  deleteStyle(id: string): Observable<void> {
    return this.http.delete<void>(`/api/styles/${id}`);
  }

  /** The style's blank slides, for the live preview. `status` is 'pending' while they render. */
  layouts(id: string): Observable<StyleLayouts> {
    return this.http.get<StyleLayouts>(`/api/styles/${id}/layouts`);
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

  /** The AI writes slide text from rough notes. Nothing is built. */
  draft(request: GenerateRequest): Observable<Draft> {
    return this.http.post<Draft>('/api/draft', request);
  }

  /** Builds the slides exactly as edited, in the style, without the AI. */
  build(request: BuildRequest): Observable<Generation> {
    return this.http.post<Generation>('/api/build', request);
  }

  getGeneration(id: string): Observable<Generation> {
    return this.http.get<Generation>(`/api/generations/${id}`);
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
