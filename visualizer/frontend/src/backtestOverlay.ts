import type {BacktestResult,Strategy} from './types';

/**
 * Trade markers and position badges must never be overlaid on a preview
 * of a DIFFERENT strategy or dataset/date selection.
 *
 * The completed backtest assigns the identical Strategy object to both
 * result.strategy and the editor state; editing creates a new object.
 * Conservative identity matching avoids false CALL OPEN/PUT OPEN indications.
 */
export function backtestOverlayCurrent(
 result:BacktestResult|null,
 editorStrategy:Strategy,
 completedScope:string|null,
 currentScope:string
):boolean{
 return result!==null&&result.strategy===editorStrategy
  &&completedScope!==null&&completedScope===currentScope;
}
