/** Abort superseded HTTP requests and ignore late responses from old requests.
 * This is UI coordination only: aborting a chart fetch does not stop a
 * completed backtest or claim to terminate server-side chart computation.
 */
export class LatestRequest {
  private generation = 0;
  private active: AbortController | null = null;

  cancel(): void {
    ++this.generation;
    this.active?.abort();
    this.active = null;
  }

  async run<T>(
    fetchValue: (signal: AbortSignal) => Promise<T>,
    onSuccess: (value: T) => void,
    onFailure: (error: unknown) => void,
    onComplete: () => void,
  ): Promise<void> {
    this.cancel();
    const generation = this.generation;
    const controller = new AbortController();
    this.active = controller;
    try {
      const value = await fetchValue(controller.signal);
      if (generation === this.generation && !controller.signal.aborted) {
        onSuccess(value);
      }
    } catch (error) {
      if (generation === this.generation && !controller.signal.aborted) {
        onFailure(error);
      }
    } finally {
      if (generation === this.generation) {
        this.active = null;
        onComplete();
      }
    }
  }
}
