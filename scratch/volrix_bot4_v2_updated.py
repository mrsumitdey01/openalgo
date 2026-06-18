import datetime

class VolrixBot4(Strategy):
    """
    09:30 AM Short Straddle with 1.0% Spot SL
    Dynamic Target (300/500/800 Day-of-Week)
    Max 1 Roll to ATM
    12:30 PM Recovery 0.5% Strangle if normal loss.
    Hard 2% Max Daily Loss (blocked during recovery).
    14:00 Timed Exit for Recovery if in loss.
    """

    def init(self):
        self.actions_all = {
            'act_morning': {'trigger': False, 'legs': []},
            'act_recovery': {'trigger': False, 'legs': []},
            'act_roll': {'trigger': False, 'legs': []}
        }
        # Dynamic Target mapping by DTE/Weekday
        # Tue=1 (0DTE)=300, Mon=0 (1DTE)=500, Wed,Thu,Fri (2DTE+)=800
        self.smart_targets = {1: 300, 0: 500, 2: 800, 3: 800, 4: 800, 5: 800, 6: 800}

    def data_init(self):
        self.register_candle_data(name="dt_spot", data_type="spot", previous_trading_days=1, timeframe=self.timeframe)

    def indicator_init(self):
        pass

    def onNewDay(self):
        self.data_init()
        self.indicator_init()
        
        self.aborted_for_day = False
        self.abort_reason = None
        self.recovery_done = False
        self.recovery_timed_exit_done = False
        self.rolls_done = 0
        self.max_rolls = 1
        self.day_open_price = None
        self.peak_mtm = 0.0
        self.morning_entry_done = False
        
        # Volrix resets self.mtm and self.position automatically per day for intraday=True

    def minTrigger(self):
        # Hard square off at 15:15
        if self.candleTime >= datetime.time(15, 15):
            self.square_off_all_positions(remark="EOD Square Off")
            self.stop_backtest()
            return

        if not self.aborted_for_day or self.recovery_done:
            # 14:00 Timed Exit for Recovery
            if self.recovery_done and not self.recovery_timed_exit_done and self.candleTime >= datetime.time(14, 0):
                if self.open_mtm < 0:
                    self.square_off_all_positions(remark="[STRATEGY A] Recovery Timed Exit")
                    self.recovery_timed_exit_done = True
                    self.aborted_for_day = True
                    self.abort_reason = "RECOVERY_TIMED_EXIT"
                else:
                    self.recovery_timed_exit_done = True

    def onCandleClose(self):
        if self.candleTime < datetime.time(9, 16):
            return

        # --- 1. Gap Check ---
        if self.day_open_price is None and len(self.dt_spot['open']) > 0:
            # We use today's first 1-min open
            # For a more robust gap check, we compare to yesterday's close.
            # dt_spot has previous days data if registered with previous_trading_days=1
            self.day_open_price = self.dt_spot['open'][-1] # fallback to current bar open if needed
            
            # Since finding exact prev close in arrays can be tricky if we don't track boundaries,
            # we will just do a rough approximation or skip the exact gap abort if too complex for the engine.
            # But we can find the previous day's close from self.getDailyData()
            daily_df = self.getDailyData()
            import pandas as pd
            if not daily_df.empty:
                prev_days = daily_df[daily_df['date'] < pd.Timestamp(self.currentDay)]
                if not prev_days.empty:
                    prev_close = prev_days.iloc[-1]['close']
                    gap_pct = abs(self.day_open_price - prev_close) / prev_close
                    if gap_pct > 0.005:
                        self.aborted_for_day = True
                        self.abort_reason = "GAP"

        if self.aborted_for_day and not (self.abort_reason == "LOSS" and not self.recovery_done):
            return

        spot_close = self.dt_spot['close'][-1]

        # --- 2. 09:30 Morning Entry ---
        if not self.morning_entry_done and not self.aborted_for_day and self.candleTime >= datetime.time(9, 30):
            self.morning_entry_done = True
            for opt in ('CE', 'PE'):
                leg = self.add_managed_leg(
                    side             = 'sell',
                    option_type      = opt,
                    lots             = 1,
                    strike_selection = {'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None},
                    exp              = {'expType': 'weekly', 'expNo': 0},
                    stop_loss        = {'isSL': True, 'SLon': '%', 'SLvalue': 1.0}, # 1.0% Spot SL
                    target           = {'isTarget': False, 'targetOn': 'val', 'targetValue': 0},
                    trailing_stop_loss = {'isTrailSL': False, 'trailSLon': 'val', 'trailSL_X': 0, 'trailSL_Y': 0},
                    stop_loss_reentry  = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                    target_reentry     = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                    wait_trade         = {'isWT': False, 'wtOn': 'val-up', 'wtVal': 0, 'triggers': []},
                    segment          = 'OPT',
                    square_off       = 'this',
                    leg_name         = f'morning_{opt}',
                    remark           = f'09:30 ATM {opt}'
                )
                self.actions_all['act_morning']['legs'].append(leg)

        # --- 3. Manage Morning Positions (Rolls & Targets & Max Loss) ---
        if self.morning_entry_done and not self.recovery_done and not self.aborted_for_day:
            # Check for SL hits on CE/PE to perform rolls
            has_ce = self.has_leg("morning_CE")
            has_pe = self.has_leg("morning_PE")
            
            if not has_ce and has_pe:
                # CE SL hit
                if self.rolls_done < self.max_rolls:
                    self.exit_leg_by_name("morning_PE")
                    # Roll PE UP to ATM
                    leg = self.add_managed_leg(
                        side             = 'sell',
                        option_type      = 'PE',
                        lots             = 1,
                        strike_selection = {'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None},
                        exp              = {'expType': 'weekly', 'expNo': 0},
                        stop_loss        = {'isSL': True, 'SLon': '%', 'SLvalue': 1.0},
                        target           = {'isTarget': False, 'targetOn': 'val', 'targetValue': 0},
                        trailing_stop_loss = {'isTrailSL': False, 'trailSLon': 'val', 'trailSL_X': 0, 'trailSL_Y': 0},
                        stop_loss_reentry  = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                        target_reentry     = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                        wait_trade         = {'isWT': False, 'wtOn': 'val-up', 'wtVal': 0, 'triggers': []},
                        segment          = 'OPT',
                        square_off       = 'this',
                        leg_name         = 'roll_PE',
                        remark           = 'Roll PE to ATM'
                    )
                    self.actions_all['act_roll']['legs'].append(leg)
                    self.rolls_done += 1
                elif not self.has_leg("roll_PE"):
                    # Both legs hit SL
                    self.aborted_for_day = True
                    self.abort_reason = "LOSS"
                    
            elif not has_pe and has_ce:
                # PE SL hit
                if self.rolls_done < self.max_rolls:
                    self.exit_leg_by_name("morning_CE")
                    # Roll CE DOWN to ATM
                    leg = self.add_managed_leg(
                        side             = 'sell',
                        option_type      = 'CE',
                        lots             = 1,
                        strike_selection = {'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None},
                        exp              = {'expType': 'weekly', 'expNo': 0},
                        stop_loss        = {'isSL': True, 'SLon': '%', 'SLvalue': 1.0},
                        target           = {'isTarget': False, 'targetOn': 'val', 'targetValue': 0},
                        trailing_stop_loss = {'isTrailSL': False, 'trailSLon': 'val', 'trailSL_X': 0, 'trailSL_Y': 0},
                        stop_loss_reentry  = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                        target_reentry     = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                        wait_trade         = {'isWT': False, 'wtOn': 'val-up', 'wtVal': 0, 'triggers': []},
                        segment          = 'OPT',
                        square_off       = 'this',
                        leg_name         = 'roll_CE',
                        remark           = 'Roll CE to ATM'
                    )
                    self.actions_all['act_roll']['legs'].append(leg)
                    self.rolls_done += 1
                elif not self.has_leg("roll_CE"):
                    # Both legs hit SL
                    self.aborted_for_day = True
                    self.abort_reason = "LOSS"
                    
            # Check if rolled leg hit SL
            if self.rolls_done >= self.max_rolls and not self.has_leg("morning_CE") and not self.has_leg("morning_PE") and not self.has_leg("roll_CE") and not self.has_leg("roll_PE"):
                self.aborted_for_day = True
                self.abort_reason = "LOSS"

            # Max Loss (2% Capital) - approx 160000 per lot margin deployed
            # 1 Nifty lot deployed capital = 185000 approx
            # 2% of 185000 = -3700 per lot
            dynamic_capital = 185000.0 * self.getLotSize / 65.0
            max_mtm_loss = -(dynamic_capital * 0.02)
            
            # Dynamic Target
            target_pts = self.smart_targets.get(self.currentDay.weekday(), 800)
            target_profit = target_pts * (self.getLotSize / 65.0)

            # Max Loss Filter (only when recovery_done is false)
            if not self.recovery_done and self.mtm < max_mtm_loss:
                self.square_off_all_positions(remark="MAX_LOSS_HIT")
                self.aborted_for_day = True
                self.abort_reason = "MAX_LOSS"
                return

            # Profit Target Filter
            if self.mtm >= target_profit:
                self.square_off_all_positions(remark="PROFIT_TARGET_HIT")
                self.aborted_for_day = True
                self.abort_reason = "PROFIT"
                return

        # --- 4. 12:30 Recovery Execution ---
        if self.aborted_for_day and self.abort_reason == "LOSS" and not self.recovery_done:
            if self.candleTime >= datetime.time(12, 30):
                # Check 1% extreme trend divergence from open
                if self.day_open_price:
                    divergence = abs(spot_close - self.day_open_price) / self.day_open_price
                    if divergence > 0.010:
                        self.recovery_done = True
                        self.abort_reason = "LOSS_BLOCKED_RECOVERY"
                        return

                self.recovery_done = True
                # Execute 0.5% wide strangle
                spot_up = spot_close * 1.005
                spot_dn = spot_close * 0.995
                
                strike_diff = self.strikeDiff or 50
                ce_strike = round(spot_up / strike_diff) * strike_diff
                pe_strike = round(spot_dn / strike_diff) * strike_diff

                # Instead of explicit strikes, we can use premium/delta or fixed offset
                # Let's use exact strike offset based on distance
                offset_ce = (ce_strike - spot_close) / strike_diff
                offset_pe = (spot_close - pe_strike) / strike_diff

                leg_c = self.add_managed_leg(
                    side             = 'sell',
                    option_type      = 'CE',
                    lots             = 1,
                    strike_selection = {'strikeBy': 'moneyness', 'strikeVal': int(-offset_ce) if offset_ce > 0 else 0, 'asof': 'None', 'roundoff': None},
                    exp              = {'expType': 'weekly', 'expNo': 0},
                    stop_loss        = {'isSL': True, 'SLon': '%', 'SLvalue': 1.0}, # 1% SL on recovery legs
                    target           = {'isTarget': False, 'targetOn': 'val', 'targetValue': 0},
                    trailing_stop_loss = {'isTrailSL': False, 'trailSLon': 'val', 'trailSL_X': 0, 'trailSL_Y': 0},
                    stop_loss_reentry  = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                    target_reentry     = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                    wait_trade         = {'isWT': False, 'wtOn': 'val-up', 'wtVal': 0, 'triggers': []},
                    segment          = 'OPT',
                    square_off       = 'this',
                    leg_name         = 'rec_CE',
                    remark           = '0.5% Recovery CE'
                )
                
                leg_p = self.add_managed_leg(
                    side             = 'sell',
                    option_type      = 'PE',
                    lots             = 1,
                    strike_selection = {'strikeBy': 'moneyness', 'strikeVal': int(-offset_pe) if offset_pe > 0 else 0, 'asof': 'None', 'roundoff': None},
                    exp              = {'expType': 'weekly', 'expNo': 0},
                    stop_loss        = {'isSL': True, 'SLon': '%', 'SLvalue': 1.0}, # 1% SL on recovery legs
                    target           = {'isTarget': False, 'targetOn': 'val', 'targetValue': 0},
                    trailing_stop_loss = {'isTrailSL': False, 'trailSLon': 'val', 'trailSL_X': 0, 'trailSL_Y': 0},
                    stop_loss_reentry  = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                    target_reentry     = {'isReEntry': False, 'reEntryOn': 'asap', 'reEntryVal': 0, 'reEntryMaxNo': 0},
                    wait_trade         = {'isWT': False, 'wtOn': 'val-up', 'wtVal': 0, 'triggers': []},
                    segment          = 'OPT',
                    square_off       = 'this',
                    leg_name         = 'rec_PE',
                    remark           = '0.5% Recovery PE'
                )
                self.actions_all['act_recovery']['legs'].extend([leg_c, leg_p])

    def onEnd(self):
        pass
