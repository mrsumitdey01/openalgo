import {
  Activity,
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  CheckCircle2,
  DollarSign,
  Info,
  Loader2,
  Percent,
  Play,
  RefreshCw,
  TrendingUp,
  LineChart,
  Bot,
  Zap,
  StopCircle,
  CircleDot
} from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import Plot from '@/lib/Plot2D'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

interface CatalogItem {
  symbol: string
  exchange: string
  interval: string
  first_timestamp: number
  last_timestamp: number
  record_count: number
  last_download_at?: string
}

interface Trade {
  id: number
  direction: 'BUY' | 'SELL'
  qty: number
  entry_time: string
  entry_price: number
  entry_fee: number
  exit_time: string
  exit_price: number
  exit_fee: number
  gross_pnl: number
  net_pnl: number
  pnl_pct: number
  exit_reason: string
}

interface ChartBar {
  timestamp: number
  datetime: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  capital: number
  fast_indicator?: number
  slow_indicator?: number
  rsi?: number
  macd_line?: number
  signal_line?: number
  macd_hist?: number
  buy_marker?: boolean
  sell_marker?: boolean
}

interface BacktestMetrics {
  initial_capital: number
  final_capital: number
  net_pnl: number
  roi_pct: number
  total_trades: number
  win_rate_pct: number
  winning_trades: number
  losing_trades: number
  profit_factor: number
  max_drawdown_pct: number
  avg_trade_pnl: number
}

interface BacktestResponse {
  status: 'success' | 'error'
  symbol: string
  exchange: string
  interval: string
  strategy: string
  metrics: BacktestMetrics
  trades: Trade[]
  chart_data: ChartBar[]
  message?: string
}


async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

export default function Backtest() {
  const { mode, appMode } = useThemeStore()
  const isDark = mode === 'dark' || appMode === 'analyzer'

  // Catalog state
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [catalogLoading, setCatalogLoading] = useState(false)

  // Form selections
  const [selectedSymbolKey, setSelectedSymbolKey] = useState('') // Format: EXCHANGE:SYMBOL
  const [selectedInterval, setSelectedInterval] = useState('')

  // Custom Bots State
  const [selectedBot, setSelectedBot] = useState('bot1')
  const [selectedBotAlgorithm, setSelectedBotAlgorithm] = useState('bot1')
  const [bot4TargetType, setBot4TargetType] = useState('fixed_1600')
  const [bot4TrendFilterPct, setBot4TrendFilterPct] = useState('1.0')
  const [bot4RecTimedExit, setBot4RecTimedExit] = useState(true)
  const [bot4RecTimedExitHour, setBot4RecTimedExitHour] = useState('14')
  const [botLotSize, setBotLotSize] = useState('30')
  const [applyBrokerage, setApplyBrokerage] = useState(true)
  const [botExecutionMode, setBotExecutionMode] = useState('options_spread')
  const [botQty, setBotQty] = useState('1')               // MCX uses plain quantity (not lot size)

  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [strategy, setStrategy] = useState('ema_crossover')

  // Derived: detect if the selected symbol is an MCX commodity
  const isMCX = selectedSymbolKey.startsWith('MCX')

  // Financial inputs
  const [capital, setCapital] = useState('100000')
  const [slippage, setSlippage] = useState('0.05')
  const [commissionFlat, setCommissionFlat] = useState('20')
  const [commissionPct, setCommissionPct] = useState('0.03')
  
  // Apply Bot 4 default constraints
  useEffect(() => {
    if (selectedBotAlgorithm === 'bot4') {
      setCapital('185000')
      setBotLotSize('65')
    }
  }, [selectedBotAlgorithm])

  // Strategy specific parameter inputs
  const [fastPeriod, setFastPeriod] = useState('9')
  const [slowPeriod, setSlowPeriod] = useState('21')
  const [rsiPeriod, setRsiPeriod] = useState('14')
  const [rsiOversold, setRsiOversold] = useState('30')
  const [rsiOverbought, setRsiOverbought] = useState('70')
  const [macdFast, setMacdFast] = useState('12')
  const [macdSlow, setMacdSlow] = useState('26')
  const [macdSignal, setMacdSignal] = useState('9')

  // Execution state
  const [running, setRunning] = useState(false)
  const [backtestResult, setBacktestResult] = useState<BacktestResponse | null>(null)
  const [visibleTradesLimit, setVisibleTradesLimit] = useState(1000)

  // Load catalog on mount
  useEffect(() => {
    loadCatalog()
  }, [])

  const loadCatalog = async () => {
    setCatalogLoading(true)
    try {
      const response = await fetch('/historify/api/catalog', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        const items: CatalogItem[] = data.data || []
        setCatalog(items)
        // Set default symbol if available
        if (items.length > 0) {
          const firstItem = items[0]
          const key = `${firstItem.exchange}:${firstItem.symbol}`
          setSelectedSymbolKey(key)
          setSelectedInterval(firstItem.interval)

          // Pre-populate date range based on that symbol's range
          if (firstItem.first_timestamp) {
            const startStr = new Date(firstItem.first_timestamp * 1000)
              .toISOString()
              .split('T')[0]
            setStartDate(startStr)
          }
          if (firstItem.last_timestamp) {
            const endStr = new Date(firstItem.last_timestamp * 1000)
              .toISOString()
              .split('T')[0]
            setEndDate(endStr)
          }
        }
      } else {
        showToast.error(data.message || 'Failed to load historical data catalog')
      }
    } catch {
      showToast.error('Error connecting to historical data service')
    } finally {
      setCatalogLoading(false)
    }
  };

  // Group catalog to show unique symbols in dropdown
  const uniqueSymbols = useMemo(() => {
    const seen = new Set<string>()
    const results: { key: string; label: string; exchange: string; symbol: string }[] = []

    for (const item of catalog) {
      const key = `${item.exchange}:${item.symbol}`
      if (!seen.has(key)) {
        seen.add(key)
        results.push({
          key,
          label: `${item.symbol} (${item.exchange})`,
          exchange: item.exchange,
          symbol: item.symbol,
        })
      }
    }
    return results
  }, [catalog])

  // Get available intervals for selected symbol
  const availableIntervals = useMemo(() => {
    if (!selectedSymbolKey) return []
    const [exchange, symbol] = selectedSymbolKey.split(':')
    return catalog
      .filter((item) => item.symbol === symbol && item.exchange === exchange)
      .map((item) => item.interval)
  }, [selectedSymbolKey, catalog])

  // Automatically update interval and dates when symbol changes
  const renderResults = () => {
    if (!backtestResult) return null;
    return (
<>
                {/* METRICS GRID */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {/* P&L CARD */}
                  <Card className="relative overflow-hidden border border-border/70 shadow-sm">
                    <CardHeader className="pb-2">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                        Net P&L (ROI %)
                      </p>
                    </CardHeader>
                    <CardContent>
                      <div
                        className={`text-2xl font-bold flex items-center gap-1 ${
                          backtestResult.metrics.net_pnl >= 0 ? 'text-emerald-500' : 'text-red-500'
                        }`}
                      >
                        {backtestResult.metrics.net_pnl >= 0 ? '+' : ''}
                        ₹{backtestResult.metrics.net_pnl.toLocaleString('en-IN')}
                        <span className="text-xs font-semibold">
                          ({backtestResult.metrics.roi_pct}%)
                        </span>
                      </div>
                      <div className="absolute right-3 bottom-3 opacity-15">
                        {backtestResult.metrics.net_pnl >= 0 ? (
                          <ArrowUpRight className="h-10 w-10 text-emerald-500" />
                        ) : (
                          <ArrowDownRight className="h-10 w-10 text-red-500" />
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  {/* WIN RATE CARD */}
                  <Card className="relative overflow-hidden border border-border/70 shadow-sm">
                    <CardHeader className="pb-2">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                        Win Rate
                      </p>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-extrabold text-foreground">
                        {backtestResult.metrics.win_rate_pct}%
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {backtestResult.metrics.winning_trades} /{' '}
                        {backtestResult.metrics.total_trades} trades
                      </p>
                      <div className="absolute right-3 bottom-3 opacity-15">
                        <CheckCircle2 className="h-10 w-10 text-primary" />
                      </div>
                    </CardContent>
                  </Card>

                  {/* DRAWDOWN CARD */}
                  <Card className="relative overflow-hidden border border-border/70 shadow-sm">
                    <CardHeader className="pb-2">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                        Max Drawdown
                      </p>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-extrabold text-red-500">
                        {backtestResult.metrics.max_drawdown_pct}%
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">Peak-to-trough risk</p>
                      <div className="absolute right-3 bottom-3 opacity-15">
                        <TrendingUp className="h-10 w-10 text-red-500 rotate-180" />
                      </div>
                    </CardContent>
                  </Card>

                  {/* PROFIT FACTOR CARD */}
                  <Card className="relative overflow-hidden border border-border/70 shadow-sm">
                    <CardHeader className="pb-2">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                        Profit Factor
                      </p>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-extrabold text-foreground">
                        {backtestResult.metrics.profit_factor}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">Gross Win / Gross Loss</p>
                      <div className="absolute right-3 bottom-3 opacity-15">
                        <TrendingUp className="h-10 w-10 text-primary" />
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* CHARTS CONTAINER */}
                <Card className="border border-border/80 shadow-md">
                  <CardContent className="p-4 space-y-4">
                    {/* Price Chart */}
                    <div>
                      <h3 className="text-sm font-bold text-muted-foreground mb-2">Price & Executions</h3>
                      {mainPlot.data.length > 0 ? (
                        <Plot
                          data={mainPlot.data}
                          layout={mainPlot.layout}
                          config={{ displayModeBar: false, responsive: true }}
                          useResizeHandler
                          style={{ width: '100%', height: '380px' }}
                        />
                      ) : (
                        <div className="h-[380px] flex items-center justify-center text-muted-foreground text-sm">
                          Error loading price chart.
                        </div>
                      )}
                    </div>

                    {/* Secondary Indicator Chart if applicable */}
                    {secondaryPlot && (
                      <div className="border-t border-border/80 pt-4">
                        <h3 className="text-sm font-bold text-muted-foreground mb-2">
                          {backtestResult.strategy.toUpperCase()} Oscillator
                        </h3>
                        <Plot
                          data={secondaryPlot.data}
                          layout={secondaryPlot.layout}
                          config={{ displayModeBar: false, responsive: true }}
                          useResizeHandler
                          style={{ width: '100%', height: '180px' }}
                        />
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* TRADES LOG TABLE */}
                <Card className="border border-border/80 shadow-md">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-md font-bold flex items-center gap-2">
                      <Info className="h-4.5 w-4.5 text-primary" /> Trades Log ({backtestResult.trades.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    {backtestResult.trades.length === 0 ? (
                      <div className="py-8 text-center text-muted-foreground text-sm">
                        No trades executed in the backtest period.
                      </div>
                    ) : (
                      <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
                        <Table>
                          <TableHeader className="bg-muted/30 sticky top-0 z-10">
                            <TableRow>
                              <TableHead className="w-12 text-center">ID</TableHead>
                              <TableHead>Dir</TableHead>
                              <TableHead>Qty</TableHead>
                              <TableHead>Entry Price
                                <span className="block text-[9px] font-normal text-muted-foreground/70">(spread value)</span>
                              </TableHead>
                              <TableHead>Entry Time</TableHead>
                              <TableHead>Exit Price
                                <span className="block text-[9px] font-normal text-muted-foreground/70">(spread value)</span>
                              </TableHead>
                              <TableHead>Exit Time</TableHead>
                              <TableHead className="text-right">Gross P&L</TableHead>
                              <TableHead className="text-right">Net P&L</TableHead>
                              <TableHead>Reason</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {backtestResult.trades.slice(0, visibleTradesLimit).map((t: any) => (
                              <TableRow key={t.id} className="hover:bg-muted/20">
                                <TableCell className="text-center font-semibold text-muted-foreground">
                                  {t.id}
                                </TableCell>
                                <TableCell>
                                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                                    t.direction === 'LONG' || t.direction === 'BUY'
                                      ? 'bg-emerald-500/15 text-emerald-500'
                                      : 'bg-red-500/15 text-red-500'
                                  }`}>
                                    {t.direction === 'LONG' ? 'BUY' : t.direction === 'SHORT' ? 'SELL' : t.direction}
                                  </span>
                                </TableCell>
                                <TableCell className="font-medium">{t.qty}</TableCell>
                                <TableCell>₹{t.entry_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                                <TableCell className="text-xs text-muted-foreground">
                                  {t.entry_time}
                                </TableCell>
                                <TableCell>₹{t.exit_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
                                <TableCell className="text-xs text-muted-foreground">
                                  {t.exit_time}
                                </TableCell>
                                <TableCell className={`text-right font-medium ${
                                  t.gross_pnl >= 0 ? 'text-emerald-500/80' : 'text-red-500/80'
                                }`}>
                                  {t.gross_pnl >= 0 ? '+' : ''}₹{t.gross_pnl?.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '-'}
                                </TableCell>
                                <TableCell
                                  className={`text-right font-bold ${
                                    t.net_pnl >= 0 ? 'text-emerald-500' : 'text-red-500'
                                  }`}
                                >
                                  {t.net_pnl >= 0 ? '+' : ''}₹{t.net_pnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                  <span className="text-[10px] block font-normal text-muted-foreground">
                                    {t.pnl_pct}%
                                  </span>
                                </TableCell>
                                <TableCell>
                                  <Badge variant="outline" className="text-[10px] font-normal">
                                    {t.exit_reason}
                                  </Badge>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        {backtestResult.trades.length > visibleTradesLimit && (
                          <div className="py-4 text-center border-t bg-muted/5 flex flex-col items-center justify-center space-y-2">
                            <span className="text-xs text-muted-foreground">
                              Showing first {visibleTradesLimit} of {backtestResult.trades.length} trades.
                            </span>
                            <Button 
                              variant="outline" 
                              size="sm"
                              onClick={() => setVisibleTradesLimit(prev => prev + 1000)}
                            >
                              Load Next 1000 Trades
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
    );
  };

  const handleSymbolChange = (key: string) => {
    setSelectedSymbolKey(key)
    const [exchange, symbol] = key.split(':')
    const matches = catalog.filter((item) => item.symbol === symbol && item.exchange === exchange)
    if (matches.length > 0) {
      // Pick first interval
      setSelectedInterval(matches[0].interval)

      // Get overall min/max timestamps for this symbol
      const firstTimestamps = matches.map((m) => m.first_timestamp).filter(Boolean)
      const lastTimestamps = matches.map((m) => m.last_timestamp).filter(Boolean)

      if (firstTimestamps.length > 0) {
        const minTs = Math.min(...firstTimestamps)
        setStartDate(new Date(minTs * 1000).toISOString().split('T')[0])
      }
      if (lastTimestamps.length > 0) {
        const maxTs = Math.max(...lastTimestamps)
        setEndDate(new Date(maxTs * 1000).toISOString().split('T')[0])
      }
    }

    // Auto-select bot and sizing defaults based on exchange/symbol
    const isMCXExchange = exchange.startsWith('MCX')
    if (isMCXExchange) {
      // MCX commodities: route to MCX bot, default qty = 1
      setSelectedBot('bot1_mcx')
      setBotQty('1')
    } else {
      // NSE indices: route to NSE bot, auto-select lot size by symbol
      setSelectedBot('bot1')
      if (symbol.includes('BANKNIFTY')) {
        setBotLotSize('30')
      } else if (symbol.includes('NIFTY')) {
        setBotLotSize('65')
      }
    }
  }

  // Handle run backtest
  const handleRunBotBacktest = async () => {
    if (!selectedSymbolKey) {
      showToast.error('Please select a symbol')
      return
    }
    if (!startDate || !endDate) {
      showToast.error('Please select start and end dates')
      return
    }

    const [exchange, symbol] = selectedSymbolKey.split(':')
    const isMCXSymbol = exchange.startsWith('MCX')

    // For MCX: use plain qty (no lot multiplier); for NSE: use lot_size
    const resolvedQty = isMCXSymbol
      ? (Number.parseInt(botQty) || 1)
      : (Number.parseInt(botLotSize) || 30)

    // Auto-route to correct bot based on exchange
    const resolvedBotId = isMCXSymbol ? `${selectedBotAlgorithm}_mcx` : selectedBotAlgorithm

    const payload = {
      bot_id: resolvedBotId,
      symbol,
      exchange,
      start_date: startDate,
      end_date: endDate,
      capital: Number.parseFloat(capital) || 100000,
      lot_size: resolvedQty,
      execution_mode: botExecutionMode,
      apply_brokerage: applyBrokerage,
      target_type: bot4TargetType, // Specific to Bot 4
      trend_filter_pct: Number.parseFloat(bot4TrendFilterPct) / 100,
      rec_timed_exit: bot4RecTimedExit,
      rec_timed_exit_hour: Number.parseInt(bot4RecTimedExitHour),
      profit_targets: bot4TargetType === 'dynamic_day_based' ? {
        "Monday": 0.008,
        "Tuesday": 0.009,
        "Wednesday": 0.009,
        "Thursday": 0.010,
        "Friday": 0.006
      } : undefined
    }

    setRunning(true)
    setBacktestResult(null)
    setVisibleTradesLimit(1000)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/backtest_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify(payload),
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        setBacktestResult(data)
        showToast.success(`Bot Backtest completed for ${symbol}! (${isMCXSymbol ? 'MCX' : 'NSE'} mode)`)
      } else {
        showToast.error(data.message || 'Bot Backtest failed')
      }
    } catch {
      showToast.error('Failed to run bot backtest simulation')
    } finally {
      setRunning(false)
    }
  }

  const handleRunBacktest = async () => {
    if (!selectedSymbolKey) {
      showToast.error('Please select a symbol')
      return
    }
    if (!selectedInterval) {
      showToast.error('Please select an interval')
      return
    }
    if (!startDate || !endDate) {
      showToast.error('Please select start and end dates')
      return
    }

    const [exchange, symbol] = selectedSymbolKey.split(':')

    // Collect parameters
    const strategyParams: Record<string, number> = {}
    if (strategy === 'sma_crossover' || strategy === 'ema_crossover') {
      strategyParams.fast_period = Number.parseInt(fastPeriod) || 9
      strategyParams.slow_period = Number.parseInt(slowPeriod) || 21
    } else if (strategy === 'rsi') {
      strategyParams.period = Number.parseInt(rsiPeriod) || 14
      strategyParams.oversold = Number.parseFloat(rsiOversold) || 30
      strategyParams.overbought = Number.parseFloat(rsiOverbought) || 70
    } else if (strategy === 'macd') {
      strategyParams.fast_period = Number.parseInt(macdFast) || 12
      strategyParams.slow_period = Number.parseInt(macdSlow) || 26
      strategyParams.signal_period = Number.parseInt(macdSignal) || 9
    }

    const payload = {
      symbol,
      exchange,
      interval: selectedInterval,
      start_date: startDate,
      end_date: endDate,
      strategy,
      strategy_params: strategyParams,
      capital: Number.parseFloat(capital) || 100000,
      slippage_pct: Number.parseFloat(slippage) || 0.05,
      commission_flat: Number.parseFloat(commissionFlat) || 20,
      commission_pct: Number.parseFloat(commissionPct) || 0.03,
    }

    setRunning(true)
    setBacktestResult(null)
    setVisibleTradesLimit(1000)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify(payload),
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        setBacktestResult(data)
        showToast.success(`Backtest completed for ${symbol}!`)
      } else {
        showToast.error(data.message || 'Backtest failed')
      }
    } catch {
      showToast.error('Failed to run backtest simulation')
    } finally {
      setRunning(false)
    }
  }

  // Layout Theme colors for Plotly
  const themeColors = useMemo(
    () => ({
      bg: 'rgba(0,0,0,0)',
      paper: 'rgba(0,0,0,0)',
      text: isDark ? '#e0e0e0' : '#333333',
      grid: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
      fastLine: '#3b82f6',
      slowLine: '#f59e0b',
      rsiLine: '#8b5cf6',
      macdLine: '#3b82f6',
      signalLine: '#ec4899',
      histUp: 'rgba(16, 185, 129, 0.6)',
      histDown: 'rgba(239, 68, 68, 0.6)',
      spotLine: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.3)',
      hoverBg: isDark ? '#1e293b' : '#ffffff',
      hoverFont: isDark ? '#e0e0e0' : '#333333',
      hoverBorder: isDark ? '#475569' : '#e2e8f0',
    }),
    [isDark]
  )

  // Configure Main Price Chart (Candlesticks + Indicators + Trade Signals)
  const mainPlot = useMemo(() => {
    if (!backtestResult?.chart_data) return { data: [], layout: {} }

    const data = backtestResult.chart_data
    const trades = backtestResult.trades

    const times = data.map((d) => d.datetime)
    const opens = data.map((d) => d.open)
    const highs = data.map((d) => d.high)
    const lows = data.map((d) => d.low)
    const closes = data.map((d) => d.close)

    const traces: PlotlyTypes.Data[] = [
      {
        x: times,
        open: opens,
        high: highs,
        low: lows,
        close: closes,
        type: 'candlestick',
        name: 'Price',
        increasing: { line: { color: '#10b981' } },
        decreasing: { line: { color: '#ef4444' } },
        line: { width: 1 },
      },
    ]

    // Overlay Fast & Slow Indicators for Crossover strategies
    if (backtestResult.strategy === 'sma_crossover' || backtestResult.strategy === 'ema_crossover') {
      const fasts = data.map((d) => d.fast_indicator)
      const slows = data.map((d) => d.slow_indicator)

      if (fasts.some((v) => v !== undefined)) {
        traces.push({
          x: times,
          y: fasts as number[],
          type: 'scatter',
          mode: 'lines',
          name: 'Fast Indicator',
          line: { color: themeColors.fastLine, width: 1.5 },
        })
      }
      if (slows.some((v) => v !== undefined)) {
        traces.push({
          x: times,
          y: slows as number[],
          type: 'scatter',
          mode: 'lines',
          name: 'Slow Indicator',
          line: { color: themeColors.slowLine, width: 1.5 },
        })
      }
    }

    // Add actual Buy and Sell Trade Marks
    if (trades && trades.length > 0) {
      const buyX: string[] = []
      const buyY: number[] = []
      const sellX: string[] = []
      const sellY: number[] = []

      for (const t of trades) {
        buyX.push(t.entry_time)
        buyY.push(t.entry_price)
        sellX.push(t.exit_time)
        sellY.push(t.exit_price)
      }

      traces.push({
        x: buyX,
        y: buyY,
        type: 'scatter',
        mode: 'markers',
        name: 'Buy Signals',
        marker: { symbol: 'triangle-up', size: 10, color: '#10b981' },
        hovertemplate: 'Buy Entry Price: %{y:.2f}<extra></extra>',
      })

      traces.push({
        x: sellX,
        y: sellY,
        type: 'scatter',
        mode: 'markers',
        name: 'Sell Signals',
        marker: { symbol: 'triangle-down', size: 10, color: '#ef4444' },
        hovertemplate: 'Sell Exit Price: %{y:.2f}<extra></extra>',
      })
    }

    const layout: Partial<PlotlyTypes.Layout> = {
      paper_bgcolor: themeColors.paper,
      plot_bgcolor: themeColors.bg,
      font: { color: themeColors.text, family: 'system-ui, sans-serif' },
      xaxis: {
        gridcolor: themeColors.grid,
        rangeslider: { visible: false },
        tickfont: { color: themeColors.text, size: 10 },
      },
      yaxis: {
        gridcolor: themeColors.grid,
        tickfont: { color: themeColors.text, size: 10 },
        title: { text: 'Price', font: { size: 12, color: themeColors.text } },
      },
      margin: { l: 50, r: 20, t: 10, b: 30 },
      hovermode: 'x unified',
      hoverlabel: {
        bgcolor: themeColors.hoverBg,
        font: { color: themeColors.hoverFont },
        bordercolor: themeColors.hoverBorder,
      },
      showlegend: true,
      legend: {
        orientation: 'h',
        x: 0.5,
        xanchor: 'center',
        y: 1.1,
        font: { size: 11 },
      },
      height: 380,
    }

    return { data: traces, layout }
  }, [backtestResult, themeColors])

  // Configure Secondary Indicator Chart (RSI or MACD Subplots)
  const secondaryPlot = useMemo(() => {
    if (!backtestResult?.chart_data) return null

    const data = backtestResult.chart_data
    const times = data.map((d) => d.datetime)

    if (backtestResult.strategy === 'rsi') {
      const rsis = data.map((d) => d.rsi)
      const oversolds = Array(times.length).fill(Number.parseInt(rsiOversold) || 30)
      const overboughts = Array(times.length).fill(Number.parseInt(rsiOverbought) || 70)

      const traces: PlotlyTypes.Data[] = [
        {
          x: times,
          y: rsis as number[],
          type: 'scatter',
          mode: 'lines',
          name: 'RSI',
          line: { color: themeColors.rsiLine, width: 1.5 },
        },
        {
          x: times,
          y: oversolds,
          type: 'scatter',
          mode: 'lines',
          name: 'Oversold (30)',
          line: { color: '#ef4444', width: 1, dash: 'dash' },
          showlegend: false,
        },
        {
          x: times,
          y: overboughts,
          type: 'scatter',
          mode: 'lines',
          name: 'Overbought (70)',
          line: { color: '#10b981', width: 1, dash: 'dash' },
          showlegend: false,
        },
      ]

      const layout: Partial<PlotlyTypes.Layout> = {
        paper_bgcolor: themeColors.paper,
        plot_bgcolor: themeColors.bg,
        font: { color: themeColors.text, family: 'system-ui, sans-serif' },
        xaxis: { gridcolor: themeColors.grid, tickfont: { color: themeColors.text, size: 10 } },
        yaxis: {
          gridcolor: themeColors.grid,
          tickfont: { color: themeColors.text, size: 10 },
          range: [0, 100],
          title: { text: 'RSI', font: { size: 12, color: themeColors.text } },
        },
        margin: { l: 50, r: 20, t: 5, b: 30 },
        hovermode: 'x unified',
        height: 180,
        showlegend: false,
      }

      return { data: traces, layout }
    }

    if (backtestResult.strategy === 'macd') {
      const macdLine = data.map((d) => d.macd_line)
      const sigLine = data.map((d) => d.signal_line)
      const hist = data.map((d) => d.macd_hist)

      // Histogram colors based on positive/negative
      const histColors = hist.map((v) =>
        (v || 0) >= 0 ? themeColors.histUp : themeColors.histDown
      )

      const traces: PlotlyTypes.Data[] = [
        {
          x: times,
          y: macdLine as number[],
          type: 'scatter',
          mode: 'lines',
          name: 'MACD',
          line: { color: themeColors.macdLine, width: 1.5 },
        },
        {
          x: times,
          y: sigLine as number[],
          type: 'scatter',
          mode: 'lines',
          name: 'Signal',
          line: { color: themeColors.signalLine, width: 1.5 },
        },
        {
          x: times,
          y: hist as number[],
          type: 'bar',
          name: 'Histogram',
          marker: { color: histColors },
        },
      ]

      const layout: Partial<PlotlyTypes.Layout> = {
        paper_bgcolor: themeColors.paper,
        plot_bgcolor: themeColors.bg,
        font: { color: themeColors.text, family: 'system-ui, sans-serif' },
        xaxis: { gridcolor: themeColors.grid, tickfont: { color: themeColors.text, size: 10 } },
        yaxis: {
          gridcolor: themeColors.grid,
          tickfont: { color: themeColors.text, size: 10 },
          title: { text: 'MACD', font: { size: 12, color: themeColors.text } },
        },
        margin: { l: 50, r: 20, t: 5, b: 30 },
        hovermode: 'x unified',
        height: 180,
        showlegend: false,
      }

      return { data: traces, layout }
    }

    return null
  }, [backtestResult, themeColors, rsiOversold, rsiOverbought])

  return (
    <div className="py-6 space-y-6 container mx-auto px-4 max-w-7xl">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between border-b border-border pb-4 gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Backtesting Lab</h1>
          <p className="text-muted-foreground mt-1">
            Simulate custom strategies on DuckDB historical data using our backtest simulator.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={loadCatalog}
            disabled={catalogLoading || running}
          >
            {catalogLoading ? (
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            Refresh Catalog
          </Button>
        </div>
      </div>

      {catalog.length === 0 && !catalogLoading && (
        <Card className="border-dashed border-2 flex flex-col items-center justify-center p-8 text-center bg-muted/20">
          <AlertCircle className="h-10 w-10 text-yellow-500 mb-3" />
          <h3 className="font-semibold text-lg">No Historical Data Available</h3>
          <p className="text-muted-foreground max-w-md mt-1 text-sm">
            Historify's local database does not have downloaded data. Please head to the{' '}
            <a href="/historify" className="text-primary hover:underline font-semibold">
              Historify page
            </a>{' '}
            to download some historical datasets first.
          </p>
        </Card>
      )}

      <Tabs defaultValue="simulator" className="w-full">
        <div className="flex justify-center mb-6">
          <TabsList className="grid w-full max-w-2xl grid-cols-3">
            <TabsTrigger value="simulator" className="flex items-center gap-2">
              <LineChart className="h-4 w-4" /> Standard Simulator
            </TabsTrigger>
            <TabsTrigger value="bots" className="flex items-center gap-2">
              <Bot className="h-4 w-4" /> Custom Bots Backtest
            </TabsTrigger>
            <TabsTrigger value="paper" className="flex items-center gap-2">
              <CircleDot className="h-4 w-4" /> Paper Trading
            </TabsTrigger>
          </TabsList>
        </div>
          
          <TabsContent value="simulator" className="mt-0">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* CONFIGURATION SIDEBAR */}
          <Card className="lg:col-span-4 border border-border/80 shadow-md">
            <CardHeader>
              <CardTitle className="text-lg font-bold flex items-center gap-2">
                <Play className="h-5 w-5 text-primary" /> Setup Parameters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Data selector */}
              <div className="space-y-2">
                <Label htmlFor="backtest-symbol">Symbol & Exchange</Label>
                <Select value={selectedSymbolKey} onValueChange={handleSymbolChange}>
                  <SelectTrigger id="backtest-symbol">
                    <SelectValue placeholder="Select Symbol" />
                  </SelectTrigger>
                  <SelectContent>
                    {uniqueSymbols.map((item) => (
                      <SelectItem key={item.key} value={item.key}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="backtest-interval">Interval</Label>
                  <Select value={selectedInterval} onValueChange={setSelectedInterval}>
                    <SelectTrigger id="backtest-interval">
                      <SelectValue placeholder="Interval" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableIntervals.map((interval) => (
                        <SelectItem key={interval} value={interval}>
                          {interval}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="backtest-strategy">Strategy</Label>
                  <Select value={strategy} onValueChange={setStrategy}>
                    <SelectTrigger id="backtest-strategy">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ema_crossover">EMA Crossover</SelectItem>
                      <SelectItem value="sma_crossover">SMA Crossover</SelectItem>
                      <SelectItem value="rsi">RSI Oversold/Bought</SelectItem>
                      <SelectItem value="macd">MACD Signal Cross</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Date pickers */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="backtest-start-date" className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5 text-muted-foreground" /> Start Date
                  </Label>
                  <Input
                    id="backtest-start-date"
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="backtest-end-date" className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5 text-muted-foreground" /> End Date
                  </Label>
                  <Input
                    id="backtest-end-date"
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                  />
                </div>
              </div>

              <div className="border-t border-border/80 my-2 pt-2" />

              {/* Financial Options */}
              <div className="space-y-3">
                <h4 className="text-sm font-semibold text-muted-foreground">Capital & Fees</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="backtest-capital">Starting Capital</Label>
                    <div className="relative">
                      <DollarSign className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="backtest-capital"
                        type="number"
                        className="pl-8"
                        value={capital}
                        onChange={(e) => setCapital(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="backtest-slippage">Slippage %</Label>
                    <div className="relative">
                      <Percent className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="backtest-slippage"
                        type="number"
                        step="0.01"
                        className="pl-8"
                        value={slippage}
                        onChange={(e) => setSlippage(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="backtest-commission-flat">Brokerage Flat (₹)</Label>
                    <Input
                      id="backtest-commission-flat"
                      type="number"
                      value={commissionFlat}
                      onChange={(e) => setCommissionFlat(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="backtest-commission-pct">Brokerage %</Label>
                    <Input
                      id="backtest-commission-pct"
                      type="number"
                      step="0.001"
                      value={commissionPct}
                      onChange={(e) => setCommissionPct(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className="border-t border-border/80 my-2 pt-2" />

              {/* Dynamic Strategy Parameters */}
              <div className="space-y-3">
                <h4 className="text-sm font-semibold text-muted-foreground">Strategy Parameters</h4>

                {(strategy === 'ema_crossover' || strategy === 'sma_crossover') && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="backtest-fast-period">Fast Period</Label>
                      <Input
                        id="backtest-fast-period"
                        type="number"
                        value={fastPeriod}
                        onChange={(e) => setFastPeriod(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="backtest-slow-period">Slow Period</Label>
                      <Input
                        id="backtest-slow-period"
                        type="number"
                        value={slowPeriod}
                        onChange={(e) => setSlowPeriod(e.target.value)}
                      />
                    </div>
                  </div>
                )}

                {strategy === 'rsi' && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-3 gap-2">
                      <div className="space-y-2">
                        <Label htmlFor="backtest-rsi-period">Period</Label>
                        <Input
                          id="backtest-rsi-period"
                          type="number"
                          value={rsiPeriod}
                          onChange={(e) => setRsiPeriod(e.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="backtest-rsi-oversold">Oversold</Label>
                        <Input
                          id="backtest-rsi-oversold"
                          type="number"
                          value={rsiOversold}
                          onChange={(e) => setRsiOversold(e.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="backtest-rsi-overbought">Overbought</Label>
                        <Input
                          id="backtest-rsi-overbought"
                          type="number"
                          value={rsiOverbought}
                          onChange={(e) => setRsiOverbought(e.target.value)}
                        />
                      </div>
                    </div>
                  </div>
                )}

                {strategy === 'macd' && (
                  <div className="grid grid-cols-3 gap-2">
                    <div className="space-y-2">
                      <Label htmlFor="backtest-macd-fast">Fast EMA</Label>
                      <Input
                        id="backtest-macd-fast"
                        type="number"
                        value={macdFast}
                        onChange={(e) => setMacdFast(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="backtest-macd-slow">Slow EMA</Label>
                      <Input
                        id="backtest-macd-slow"
                        type="number"
                        value={macdSlow}
                        onChange={(e) => setMacdSlow(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="backtest-macd-signal">Signal Period</Label>
                      <Input
                        id="backtest-macd-signal"
                        type="number"
                        value={macdSignal}
                        onChange={(e) => setMacdSignal(e.target.value)}
                      />
                    </div>
                  </div>
                )}
              </div>

              <Button
                className="w-full mt-4 bg-primary text-primary-foreground font-semibold"
                size="lg"
                onClick={handleRunBacktest}
                disabled={running}
              >
                {running ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    Running Simulation...
                  </>
                ) : (
                  <>
                    <Play className="mr-2 h-5 w-5" />
                    Execute Backtest
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* MAIN RESULTS DISPLAY */}
          <div className="lg:col-span-8 space-y-6">
            {!backtestResult && !running && (
              <Card className="flex flex-col items-center justify-center p-16 text-center border-dashed border-2 bg-muted/5 h-[400px]">
                <Activity className="h-12 w-12 text-muted-foreground/60 mb-4 animate-pulse" />
                <h3 className="font-bold text-lg text-muted-foreground">Simulation Lab Standby</h3>
                <p className="text-muted-foreground/80 max-w-sm text-sm mt-1">
                  Adjust your parameters on the left and hit <strong>Execute Backtest</strong> to run an event-driven backtest.
                </p>
              </Card>
            )}

            {running && (
              <Card className="flex flex-col items-center justify-center p-16 text-center bg-muted/5 h-[400px]">
                <Loader2 className="h-12 w-12 text-primary mb-4 animate-spin" />
                <h3 className="font-bold text-lg text-primary">Running Backtest Engine</h3>
                <p className="text-muted-foreground max-w-sm text-sm mt-1">
                  Retrieving candles, calculating technical indicators, and executing simulated trades...
                </p>
              </Card>
            )}

            {renderResults()}
          </div>
        </div>
        </TabsContent>
        
        <TabsContent value="bots" className="mt-0">

          <div className="mb-6">
            {selectedBot === 'bot1' && (
              <div className="space-y-4">
                <Alert className="bg-primary/5 border-primary/20">
                  <Info className="h-5 w-5 text-primary" />
                  <AlertTitle className="text-primary font-bold text-lg">Bot 1: Hull BBI + DTC Ribbon Options Spread</AlertTitle>
                  <AlertDescription className="mt-2 text-sm text-muted-foreground">
                    A high-frequency trend-following engine combining the Hull Bull-Bear Indicator (BBI) and Dynamic Trend Channel (DTC) Volatility Ribbons. 
                    Unlike simple naked buying, this bot executes risk-defined <strong>Options Spreads</strong> (Bull Call & Bear Put Spreads) dynamically chosen at the nearest expiry.
                  </AlertDescription>
                </Alert>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Card className="border border-border/60 shadow-sm bg-background/50">
                    <CardHeader className="pb-2 border-b border-border/30">
                      <CardTitle className="text-base flex items-center gap-2"><Activity className="h-4 w-4 text-emerald-500" /> How It Runs</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-3 text-sm text-muted-foreground space-y-2">
                      <p><strong>Tick-by-Tick Engine:</strong> In live mode, it operates as a background daemon capturing tick data continuously. It evaluates conditions strictly on the <strong>1-Minute Candle Close</strong> to prevent false intra-candle noise breakouts.</p>
                      <p><strong>Spread Selection:</strong> Resolves the precise ATM and OTM strikes autonomously by pinging the broker API for real-time nearest expiry data.</p>
                    </CardContent>
                  </Card>

                  <Card className="border border-border/60 shadow-sm bg-background/50">
                    <CardHeader className="pb-2 border-b border-border/30">
                      <CardTitle className="text-base flex items-center gap-2"><TrendingUp className="h-4 w-4 text-primary" /> Signal Logic</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-3 text-sm text-muted-foreground">
                      <ul className="list-disc list-outside ml-4 space-y-1.5">
                        <li><strong>Long Entry:</strong> Price closes ABOVE Hull BBI, BBI slope turns Blue, and price breaks ABOVE the DTC Max Ribbon. 
                          <span className="font-semibold text-primary block mt-1">
                            Action: {botExecutionMode === 'options_spread' && 'Buy Bull Call Spread'}
                                   {botExecutionMode === 'options_buying' && 'Buy ATM Call Option'}
                                   {botExecutionMode === 'options_selling' && 'Sell ATM Put Option'}
                                   {botExecutionMode === 'futures' && 'Go Long Future'}
                          </span>
                        </li>
                        <li><strong>Short Entry:</strong> Price closes BELOW Hull BBI, BBI slope turns Red, and price breaks BELOW the DTC Min Ribbon.
                          <span className="font-semibold text-primary block mt-1">
                            Action: {botExecutionMode === 'options_spread' && 'Buy Bear Put Spread'}
                                   {botExecutionMode === 'options_buying' && 'Buy ATM Put Option'}
                                   {botExecutionMode === 'options_selling' && 'Sell ATM Call Option'}
                                   {botExecutionMode === 'futures' && 'Go Short Future'}
                          </span>
                        </li>
                        <li><strong>Exit Strategy:</strong> Exits on structural stop (candle close BELOW BBI for Longs, ABOVE BBI for Shorts) or if an opposing trend change is detected. Hard Square-off executes before market close.</li>
                      </ul>
                    </CardContent>
                  </Card>
                </div>

                <Card className="border border-border/60 shadow-sm bg-background/50">
                  <CardHeader className="pb-2 border-b border-border/30">
                    <CardTitle className="text-base flex items-center gap-2"><Zap className="h-4 w-4 text-amber-500" /> Smart Order Execution & Chasing Algorithm</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-3 text-sm text-muted-foreground space-y-3">
                    <p>Options spreads require two simultaneous executions. The bot uses a <strong>Place-and-Chase</strong> algorithm to combat slippage and liquidity gaps:</p>
                    <ul className="list-decimal list-outside ml-4 space-y-2">
                      <li><strong>Dynamic Limit Ordering:</strong> Captures the Last Traded Price (LTP) via WebSocket and places strict Limit orders (avoiding dangerous Market orders on illiquid strikes).</li>
                      <li><strong>Order Chasing:</strong> If the order remains unfilled after a timeout loop (due to sudden volatility), it automatically cancels, fetches the fresh LTP, and re-places the limit orderâ€”"chasing" the price up to a defined slippage tolerance.</li>
                      <li><strong>Leg Reconciliation (Emergency Unwind):</strong> If the BUY leg fills but the SELL leg continuously fails (e.g. hitting circuit limits or extreme illiquidity), the bot prevents naked exposure by initiating an <em>Emergency Unwind</em>, immediately firing a closing market/limit order to reverse the filled BUY leg.</li>
                    </ul>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            <Card className="lg:col-span-4 border border-border/80 shadow-md">
              <CardHeader>
                <CardTitle className="text-lg font-bold flex items-center gap-2">
                  <Play className="h-5 w-5 text-primary" /> Run Bot Backtest
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="bot-backtest-symbol">Symbol & Exchange</Label>
                  <Select value={selectedSymbolKey} onValueChange={handleSymbolChange}>
                    <SelectTrigger id="bot-backtest-symbol">
                      <SelectValue placeholder="Select Symbol" />
                    </SelectTrigger>
                    <SelectContent>
                      {uniqueSymbols.map((item) => (
                        <SelectItem key={item.key} value={item.key}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {/* Exchange badge indicator */}
                  {selectedSymbolKey && (
                    <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                      isMCX
                        ? 'bg-orange-500/15 text-orange-500 border border-orange-500/30'
                        : 'bg-blue-500/15 text-blue-500 border border-blue-500/30'
                    }`}>
                      <span className="w-1.5 h-1.5 rounded-full bg-current" />
                      {isMCX ? 'MCX â€” Commodity Mode (10:00 AM â€“ 10:30 PM)' : 'NSE â€” Equity Mode (09:30 AM â€“ 03:15 PM)'}
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="bot-backtest-start-date">Start Date</Label>
                    <Input id="bot-backtest-start-date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="bot-backtest-end-date">End Date</Label>
                    <Input id="bot-backtest-end-date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="bot-backtest-capital">Starting Capital</Label>
                    <div className="relative">
                      <DollarSign className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input id="bot-backtest-capital" type="number" className="pl-8" value={capital} onChange={(e) => setCapital(e.target.value)} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    {isMCX ? (
                      // MCX: plain quantity input (no lot size system)
                      <>
                        <Label htmlFor="bot-mcx-qty">Quantity (QTY)</Label>
                        <Input
                          id="bot-mcx-qty"
                          type="number"
                          min="1"
                          step="1"
                          value={botQty}
                          onChange={(e) => setBotQty(e.target.value)}
                          placeholder="Enter quantity"
                        />
                        <p className="text-[10px] text-muted-foreground">MCX uses quantity, not lot size</p>
                      </>
                    ) : (
                      // NSE: lot size dropdown
                      <>
                        <Label htmlFor="bot-lot-size">Lot Size</Label>
                        <Select value={botLotSize} onValueChange={setBotLotSize}>
                          <SelectTrigger id="bot-lot-size">
                            <SelectValue placeholder="Select Lot Size" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="30">30 (BankNifty)</SelectItem>
                            <SelectItem value="65">65 (Nifty)</SelectItem>
                            <SelectItem value="15">15 (BankNifty Old)</SelectItem>
                            <SelectItem value="25">25 (Nifty Old)</SelectItem>
                            <SelectItem value="75">75 (Nifty Older)</SelectItem>
                            <SelectItem value="1">1 (Stocks)</SelectItem>
                          </SelectContent>
                        </Select>
                      </>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Algorithm</Label>
                  <Select value={selectedBotAlgorithm} onValueChange={setSelectedBotAlgorithm}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select Algorithm" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="bot1">Bot 1 (Hull + DTC)</SelectItem>
                      <SelectItem value="bot2">Bot 2 (EMA Momentum)</SelectItem>
                      <SelectItem value="bot3">Bot 3 (DTC Reversal SAR)</SelectItem>
                      <SelectItem value="bot4">Bot 4 (Straddle Seller)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {selectedBotAlgorithm === 'bot4' && (
                  <div className="space-y-2">
                    <Label>Profit Target Mode</Label>
                    <Select value={bot4TargetType} onValueChange={setBot4TargetType}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select Target" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="fixed_1600">Smart Dynamic Target (₹300/₹500/₹800 per lot)</SelectItem>
                        <SelectItem value="pct_capital">0.5% of Deployed Capital</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
                
                {selectedBotAlgorithm === 'bot4' && (
                  <div className="space-y-2">
                    <Label>Extreme Trend Filter (%)</Label>
                    <Input 
                      type="number" 
                      step="0.1" 
                      value={bot4TrendFilterPct} 
                      onChange={(e) => setBot4TrendFilterPct(e.target.value)} 
                    />
                  </div>
                )}

                {selectedBotAlgorithm === 'bot4' && (
                  <div className="space-y-2">
                    <Label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={bot4RecTimedExit}
                        onChange={(e) => setBot4RecTimedExit(e.target.checked)}
                        className="h-4 w-4"
                      />
                      Recovery Timed Exit (Strategy A)
                    </Label>
                    {bot4RecTimedExit && (
                      <div className="flex items-center gap-2 pl-6">
                        <Label className="text-sm text-muted-foreground">Exit at hour:</Label>
                        <Input
                          type="number"
                          min="13"
                          max="15"
                          step="1"
                          value={bot4RecTimedExitHour}
                          onChange={(e) => setBot4RecTimedExitHour(e.target.value)}
                          className="w-20"
                        />
                        <span className="text-xs text-muted-foreground">:00 IST (if in loss)</span>
                      </div>
                    )}
                  </div>
                )}

                {selectedBotAlgorithm !== 'bot4' && (
                  <div className="space-y-2">
                    <Label>Execution Mode</Label>
                    <Select value={botExecutionMode} onValueChange={setBotExecutionMode}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select Mode" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="options_spread">Options Spread</SelectItem>
                        <SelectItem value="options_buying">Options Buying (Naked)</SelectItem>
                        <SelectItem value="options_selling">Options Selling (Naked)</SelectItem>
                        <SelectItem value="futures">Futures</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}

                <div className="flex items-center space-x-2 pt-4">
                  <Switch id="apply-brokerage" checked={applyBrokerage} onCheckedChange={setApplyBrokerage} />
                  <Label htmlFor="apply-brokerage" className="cursor-pointer">Apply Flat Brokerage Fee (Rs 20)</Label>
                </div>

                {/* Active bot indicator */}
                <div className="rounded-md bg-muted/40 border px-3 py-2 text-xs text-muted-foreground">
                  <span className="font-semibold">Active Engine: </span>
                  {selectedBotAlgorithm === 'bot4'
                    ? `BOT 4 NSE — 09:30 AM Short Straddle`
                    : selectedBotAlgorithm === 'bot3'
                    ? (isMCX ? `BOT 3 MCX — DTC Reversal SAR` : `BOT 3 NSE — DTC Reversal SAR`)
                    : selectedBotAlgorithm === 'bot2' 
                    ? (isMCX ? `BOT 2 MCX — EMA Momentum Holy Grail` : `BOT 2 NSE — EMA Momentum Holy Grail`)
                    : (isMCX ? `BOT 1 MCX — Hull BBI + DTC Ribbon (Commodity)` : `BOT 1 NSE — Hull BBI + DTC Ribbon (Equity)`)
                  }
                </div>

                <Button className="w-full mt-2 bg-primary text-primary-foreground font-semibold" size="lg" onClick={handleRunBotBacktest} disabled={running}>
                  {running ? <><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Running...</> : <><Play className="mr-2 h-5 w-5" /> Run Bot Backtest</>}
                </Button>
              </CardContent>
            </Card>

            <div className="lg:col-span-8 space-y-6">
              {!backtestResult && !running && (
                <Card className="flex flex-col items-center justify-center p-16 text-center border-dashed border-2 bg-muted/5 h-[400px]">
                  <Activity className="h-12 w-12 text-muted-foreground/60 mb-4 animate-pulse" />
                  <h3 className="font-bold text-lg text-muted-foreground">Bot Lab Standby</h3>
                  <p className="text-muted-foreground/80 max-w-sm text-sm mt-1">Adjust parameters on the left and hit Run.</p>
                </Card>
              )}
              {running && (
                <Card className="flex flex-col items-center justify-center p-16 text-center bg-muted/5 h-[400px]">
                  <Loader2 className="h-12 w-12 text-primary mb-4 animate-spin" />
                  <h3 className="font-bold text-lg text-primary">Running Backtest Engine</h3>
                </Card>
              )}
              {renderResults()}
            </div>
          </div>
        </TabsContent>

        {/* â”€â”€â”€ PAPER TRADE TAB â”€â”€â”€ */}
        <TabsContent value="paper" className="mt-0">
          <PaperTradePanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// â”€â”€â”€ Paper Trade Panel Component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
interface PaperTradeAccount {
  account_id: string
  bot: string
  exchange: string
  symbol: string
  execution_mode: string
  status: string
  error?: string
  metrics: {
    initial_capital: number
    final_capital: number
    net_pnl: number
    roi_pct: number
    total_trades: number
    win_rate_pct: number
    winning_trades: number
    losing_trades: number
    profit_factor: number
    max_drawdown_pct: number
    avg_trade_pnl: number
    profitable_days: number
    total_days: number
  }
  has_open_position: boolean
}

interface PaperTradeStatusResponse {
  status: string
  is_active: boolean
  is_running: boolean
  started_at: string | null
  stopped_at: string | null
  last_run_at: string | null
  error: string | null
  total_accounts: number
  accounts: PaperTradeAccount[]
}

function PaperTradePanel() {
  const [status, setStatus] = useState<PaperTradeStatusResponse | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [filterBot, setFilterBot] = useState('all')
  const [filterExchange, setFilterExchange] = useState('all')

  const fetchStatus = useCallback(async () => {
    try {
      const csrfToken = await fetchCSRFTokenForPaper()
      const res = await fetch('/historify/api/paper_trade/status', {
        credentials: 'include',
        headers: { 'X-CSRFToken': csrfToken },
      })
      const data = await res.json()
      setStatus(data)
    } catch (err) {
      console.error('Failed to fetch paper trade status:', err)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 5000) // Poll every 5s
    return () => clearInterval(interval)
  }, [fetchStatus])

  const handleStart = async () => {
    setActionLoading(true)
    try {
      const csrfToken = await fetchCSRFTokenForPaper()
      await fetch('/historify/api/paper_trade/start', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      })
      setTimeout(fetchStatus, 1000)
    } catch (err) {
      console.error('Failed to start paper trading:', err)
    } finally {
      setActionLoading(false)
    }
  }

  const handleStop = async () => {
    setActionLoading(true)
    try {
      const csrfToken = await fetchCSRFTokenForPaper()
      await fetch('/historify/api/paper_trade/stop', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      })
      setTimeout(fetchStatus, 500)
    } catch (err) {
      console.error('Failed to stop paper trading:', err)
    } finally {
      setActionLoading(false)
    }
  }

  const isActive = status?.is_active || false
  const isRunning = status?.is_running || false
  const accounts = status?.accounts || []

  // Apply filters
  const filteredAccounts = accounts.filter(a => {
    if (filterBot !== 'all' && a.bot !== filterBot) return false
    if (filterExchange !== 'all' && a.exchange !== filterExchange) return false
    return true
  })

  // Summary stats
  const totalPnl = accounts.reduce((s, a) => s + (a.metrics?.net_pnl || 0), 0)
  const profitableAccounts = accounts.filter(a => (a.metrics?.net_pnl || 0) > 0).length
  const totalTrades = accounts.reduce((s, a) => s + (a.metrics?.total_trades || 0), 0)

  const botLabel = (bot: string) => {
    if (bot === 'bot1') return 'Bot 1 (Hull+DTC)'
    if (bot === 'bot1_mcx') return 'Bot 1 (MCX Hull)'
    if (bot === 'bot2') return 'Bot 2 (EMA Mom)'
    if (bot === 'bot2_mcx') return 'Bot 2 (MCX EMA)'
    if (bot === 'bot3') return 'Bot 3 (DTC SAR)'
    if (bot === 'bot3_mcx') return 'Bot 3 (MCX SAR)'
    if (bot === 'bot4') return 'Bot 4 (Straddle Seller)'
    return bot
  }

  const modeLabel = (mode: string) => {
    if (mode === 'futures') return 'Futures'
    if (mode === 'options_buying') return 'Opt Buy'
    if (mode === 'options_selling') return 'Opt Sell'
    if (mode === 'options_spread') return 'Spread'
    return mode
  }

  return (
    <div className="space-y-6">
      {/* Status Banner */}
      <Card className={`border-2 ${
        isActive
          ? isRunning
            ? 'border-amber-500/50 bg-amber-500/5'
            : 'border-green-500/50 bg-green-500/5'
          : 'border-border/50 bg-muted/5'
      }`}>
        <CardContent className="py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className={`h-4 w-4 rounded-full ${
                isActive
                  ? isRunning
                    ? 'bg-amber-500 animate-pulse'
                    : 'bg-green-500'
                  : 'bg-muted-foreground/30'
              }`} />
              <div>
                <h2 className="text-xl font-bold">
                  {isActive
                    ? isRunning
                      ? 'Paper Trade Engine Running...'
                      : 'Paper Trade Active'
                    : 'Paper Trade Inactive'
                  }
                </h2>
                <p className="text-sm text-muted-foreground">
                  {isActive && status?.started_at && `Started: ${status.started_at}`}
                  {!isActive && status?.stopped_at && `Last stopped: ${status.stopped_at}`}
                  {!isActive && !status?.stopped_at && 'Click Start to run all 3 bots across all execution modes'}
                </p>
                {status?.last_run_at && (
                  <p className="text-xs text-muted-foreground/70 mt-1">Last completed: {status.last_run_at}</p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={fetchStatus}
                disabled={actionLoading}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
              {!isActive ? (
                <Button
                  onClick={handleStart}
                  disabled={actionLoading}
                  className="bg-green-600 hover:bg-green-700 text-white"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <Play className="h-4 w-4 mr-2" />
                  )}
                  Start Paper Trading
                </Button>
              ) : (
                <Button
                  onClick={handleStop}
                  disabled={actionLoading}
                  variant="destructive"
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <StopCircle className="h-4 w-4 mr-2" />
                  )}
                  Stop
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary Cards */}
      {accounts.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6">
              <div className="text-sm text-muted-foreground">Total Accounts</div>
              <div className="text-2xl font-bold">{accounts.length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-sm text-muted-foreground">Combined P&L</div>
              <div className={`text-2xl font-bold ${totalPnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                ₹{totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-sm text-muted-foreground">Profitable Accounts</div>
              <div className="text-2xl font-bold text-green-500">
                {profitableAccounts} / {accounts.length}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-sm text-muted-foreground">Total Trades</div>
              <div className="text-2xl font-bold">{totalTrades.toLocaleString()}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters */}
      {accounts.length > 0 && (
        <div className="flex gap-4 flex-wrap">
          <Select value={filterBot} onValueChange={setFilterBot}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Filter by Bot" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Bots</SelectItem>
              <SelectItem value="bot1">Bot 1 (Hull+DTC)</SelectItem>
              <SelectItem value="bot2">Bot 2 (EMA Mom)</SelectItem>
              <SelectItem value="bot3">Bot 3 (DTC SAR)</SelectItem>
              <SelectItem value="bot4">Bot 4 (Straddle)</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterExchange} onValueChange={setFilterExchange}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Filter by Exchange" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Exchanges</SelectItem>
              <SelectItem value="NSE">NSE</SelectItem>
              <SelectItem value="MCX">MCX</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Results Table */}
      {filteredAccounts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Performance Dashboard ({filteredAccounts.length} accounts)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Bot</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead className="text-right">Trades</TableHead>
                    <TableHead className="text-right">Win Rate</TableHead>
                    <TableHead className="text-right">Net P&L</TableHead>
                    <TableHead className="text-right">ROI %</TableHead>
                    <TableHead className="text-right">Max DD %</TableHead>
                    <TableHead className="text-right">Profit Factor</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredAccounts.map((acc) => {
                    const m = acc.metrics
                    const pnl = m?.net_pnl || 0
                    return (
                      <TableRow key={acc.account_id} className={pnl > 0 ? 'bg-green-500/5' : pnl < 0 ? 'bg-red-500/5' : ''}>
                        <TableCell className="font-medium">{botLabel(acc.bot)}</TableCell>
                        <TableCell>
                          <Badge variant={acc.exchange === 'NSE' ? 'default' : 'secondary'}>
                            {acc.exchange}
                          </Badge>
                        </TableCell>
                        <TableCell>{acc.symbol}</TableCell>
                        <TableCell>{modeLabel(acc.execution_mode)}</TableCell>
                        <TableCell className="text-right">{m?.total_trades || 0}</TableCell>
                        <TableCell className="text-right">
                          <span className={(m?.win_rate_pct || 0) >= 50 ? 'text-green-500' : 'text-red-500'}>
                            {(m?.win_rate_pct || 0).toFixed(1)}%
                          </span>
                        </TableCell>
                        <TableCell className={`text-right font-semibold ${pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                          ₹{pnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </TableCell>
                        <TableCell className={`text-right ${(m?.roi_pct || 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                          {(m?.roi_pct || 0).toFixed(1)}%
                        </TableCell>
                        <TableCell className="text-right text-red-500">
                          {(m?.max_drawdown_pct || 0).toFixed(1)}%
                        </TableCell>
                        <TableCell className="text-right">{(m?.profit_factor || 0).toFixed(2)}</TableCell>
                        <TableCell className="text-center">
                          {acc.status === 'ok' ? (
                            acc.has_open_position ? (
                              <Badge variant="outline" className="border-amber-500 text-amber-500">In Position</Badge>
                            ) : (
                              <Badge variant="outline" className="border-green-500 text-green-500">Flat</Badge>
                            )
                          ) : acc.status === 'error' ? (
                            <Badge variant="destructive">Error</Badge>
                          ) : acc.status === 'no_data' ? (
                            <Badge variant="secondary">No Data</Badge>
                          ) : acc.status?.startsWith('CRITICAL') ? (
                            <Badge variant="destructive" title={acc.status}>⚠ Disconnected</Badge>
                          ) : acc.status?.startsWith('Stopped') ? (
                            <Badge variant="outline" className="border-blue-500 text-blue-400" title={acc.status}>
                              {acc.status.replace('Stopped (', '').replace(')', '') || 'Stopped'}
                            </Badge>
                          ) : acc.status?.startsWith('Daemon Offline') ? (
                            <Badge variant="secondary" title={acc.status}>Offline (Mkt Closed)</Badge>
                          ) : acc.status?.startsWith('Live Monitoring') ? (
                            <Badge variant="outline" className="border-green-500 text-green-400" title={acc.status}>● Live</Badge>
                          ) : (
                            <Badge variant="secondary" className="max-w-[120px] truncate" title={acc.status}>{acc.status === 'pending' ? 'Pending' : acc.status}</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty State */}
      {!isActive && accounts.length === 0 && (
        <Card className="flex flex-col items-center justify-center p-16 text-center border-dashed border-2 bg-muted/5 h-[400px]">
          <CircleDot className="h-12 w-12 text-muted-foreground/60 mb-4" />
          <h3 className="font-bold text-lg text-muted-foreground">Paper Trade Standby</h3>
          <p className="text-muted-foreground/80 max-w-md text-sm mt-2">
            Start paper trading to run all 3 bots (Hull+DTC, EMA Momentum, DTC SAR) across
            futures, options buying, selling, and spreads for NSE and MCX.
            Each account starts with ₹8,00,000 virtual capital.
          </p>
        </Card>
      )}

      {/* Running State */}
      {isRunning && accounts.length === 0 && (
        <Card className="flex flex-col items-center justify-center p-16 text-center bg-muted/5 h-[400px]">
          <Loader2 className="h-12 w-12 text-primary mb-4 animate-spin" />
          <h3 className="font-bold text-lg text-primary">Processing All Accounts...</h3>
          <p className="text-muted-foreground/80 text-sm mt-1">
            Running 3 bots Ã— 4 modes Ã— multiple symbols. This may take a few minutes.
          </p>
        </Card>
      )}
    </div>
  )
}

async function fetchCSRFTokenForPaper(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}
