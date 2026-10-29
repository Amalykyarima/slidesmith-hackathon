import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { GenerateRequest, Generation, Health, SlideContent, SlideStyle, UploadedImage } from './models';

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

  /** Builds edited slides again in the same style, without calling the AI. Returns a new generation. */
  rebuild(id: string, slides: SlideContent[]): Observable<Generation> {
    return this.http.post<Generation>(`/api/generations/${id}/rebuild`, { slides });
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
