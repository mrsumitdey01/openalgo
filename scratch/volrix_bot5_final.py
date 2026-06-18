import datetime

class VolrixBot5_Final(Strategy):
    """
    Final Verified Bot 5 Logic (NIFTY)
    Perfectly matched to Bot 4's winning logic, but compatible with Volrix v2 engine.
    """
    def init(self):
        self.actions_all = {
            'act_morning': {'trigger': False, 'legs': []},
            'act_recovery': {'trigger': False, 'legs': []},
            'act_roll': {'trigger': False, 'legs': []}
        }
        self.smart_targets = {0: 500, 1: 300, 2: 800, 3: 800, 4: 800}

    def data_init(self):
        self.register_candle_data(name="dt_spot", data_type="spot", previous_trading_days=1, timeframe=self.timeframe)

    def onNewDay(self):
        self.data_init()
        self.aborted_for_day = False
        self.abort_reason = None
        self.recovery_done = False
        self.recovery_timed_exit_done = False
        self.rolls_done = 0
        self.max_rolls = 1
        self.day_open_price = None
        self.morning_entry_done = False
        self.sl_targets = {}

    def minTrigger(self):
        if self.candleTime >= datetime.time(15, 15):
            self.square_off_all_positions(remark="EOD exit")
            self.stop_backtest()
            return
        if not self.aborted_for_day or self.recovery_done:
            if self.recovery_done and not self.recovery_timed_exit_done and self.candleTime >= datetime.time(14, 0):
                if self.open_mtm < 0:
                    self.square_off_all_positions(remark="[STRATEGY A] Recovery Timed Exit")
                    self.recovery_timed_exit_done = True
                    self.aborted_for_day = True
                    self.abort_reason = "RECOVERY_TIMED_EXIT"
                else:
                    self.recovery_timed_exit_done = True

    def onCandleClose(self):
        if len(self.dt_spot['close']) == 0:
            return
        spot_close = self.dt_spot['close'][-1]
        if self.candleTime < datetime.time(9, 16):
            return
        if self.day_open_price is None and len(self.dt_spot['open']) > 0:
            self.day_open_price = self.dt_spot['open'][-1]
        if self.aborted_for_day and not (self.abort_reason == "LOSS" and not self.recovery_done):
            return
        if not self.morning_entry_done and not self.aborted_for_day and self.candleTime >= datetime.time(9, 30):
            self.morning_entry_done = True
            self.sl_targets['morning_CE'] = spot_close * 1.01
            self.sl_targets['morning_PE'] = spot_close * 0.99
            leg_ce = self.add_managed_leg(side='sell', option_type='CE', lots=1, strike_selection={'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None}, exp={'expType': 'weekly', 'expNo': 0}, stop_loss={'isSL': False}, target={'isTarget': False}, trailing_stop_loss={'isTrailSL': False}, stop_loss_reentry={'isReEntry': False}, target_reentry={'isReEntry': False}, wait_trade={'isWT': False}, segment='OPT', square_off='this', leg_name='morning_CE', remark='09:30 ATM CE')
            leg_pe = self.add_managed_leg(side='sell', option_type='PE', lots=1, strike_selection={'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None}, exp={'expType': 'weekly', 'expNo': 0}, stop_loss={'isSL': False}, target={'isTarget': False}, trailing_stop_loss={'isTrailSL': False}, stop_loss_reentry={'isReEntry': False}, target_reentry={'isReEntry': False}, wait_trade={'isWT': False}, segment='OPT', square_off='this', leg_name='morning_PE', remark='09:30 ATM PE')
            self.actions_all['act_morning']['legs'].extend([leg_ce, leg_pe])
        if self.morning_entry_done and not self.recovery_done and not self.aborted_for_day:
            m_ce = self.get_latest_leg("morning_CE")
            m_pe = self.get_latest_leg("morning_PE")
            r_ce = self.get_latest_leg("roll_CE")
            r_pe = self.get_latest_leg("roll_PE")
            if m_ce and m_ce.is_open and spot_close >= self.sl_targets.get('morning_CE', float('inf')):
                m_ce.exitTrade(remark="Spot SL CE")
            if m_pe and m_pe.is_open and spot_close <= self.sl_targets.get('morning_PE', 0):
                m_pe.exitTrade(remark="Spot SL PE")
            if r_ce and r_ce.is_open and spot_close >= self.sl_targets.get('roll_CE', float('inf')):
                r_ce.exitTrade(remark="Spot SL Roll CE")
            if r_pe and r_pe.is_open and spot_close <= self.sl_targets.get('roll_PE', 0):
                r_pe.exitTrade(remark="Spot SL Roll PE")
            has_ce = (m_ce and m_ce.is_open) or (r_ce and r_ce.is_open)
            has_pe = (m_pe and m_pe.is_open) or (r_pe and r_pe.is_open)
            if not has_ce and has_pe:
                if self.rolls_done < self.max_rolls:
                    if m_pe and m_pe.is_open: m_pe.exitTrade(remark="Roll PE")
                    self.sl_targets['roll_PE'] = spot_close * 0.99
                    new_pe = self.add_managed_leg(side='sell', option_type='PE', lots=1, strike_selection={'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None}, exp={'expType': 'weekly', 'expNo': 0}, stop_loss={'isSL': False}, target={'isTarget': False}, trailing_stop_loss={'isTrailSL': False}, stop_loss_reentry={'isReEntry': False}, target_reentry={'isReEntry': False}, wait_trade={'isWT': False}, segment='OPT', square_off='this', leg_name='roll_PE', remark='Rolled PE to ATM')
                    self.actions_all['act_roll']['legs'].append(new_pe)
                    self.rolls_done += 1
                elif not (r_pe and r_pe.is_open) and not (m_pe and m_pe.is_open):
                    self.aborted_for_day = True
                    self.abort_reason = "LOSS"
            elif not has_pe and has_ce:
                if self.rolls_done < self.max_rolls:
                    if m_ce and m_ce.is_open: m_ce.exitTrade(remark="Roll CE")
                    self.sl_targets['roll_CE'] = spot_close * 1.01
                    new_ce = self.add_managed_leg(side='sell', option_type='CE', lots=1, strike_selection={'strikeBy': 'moneyness', 'strikeVal': 0, 'asof': 'None', 'roundoff': None}, exp={'expType': 'weekly', 'expNo': 0}, stop_loss={'isSL': False}, target={'isTarget': False}, trailing_stop_loss={'isTrailSL': False}, stop_loss_reentry={'isReEntry': False}, target_reentry={'isReEntry': False}, wait_trade={'isWT': False}, segment='OPT', square_off='this', leg_name='roll_CE', remark='Rolled CE to ATM')
                    self.actions_all['act_roll']['legs'].append(new_ce)
                    self.rolls_done += 1
                elif not (r_ce and r_ce.is_open) and not (m_ce and m_ce.is_open):
                    self.aborted_for_day = True
                    self.abort_reason = "LOSS"
            if self.rolls_done >= self.max_rolls and not has_ce and not has_pe:
                self.aborted_for_day = True
                self.abort_reason = "LOSS"
            try:
                ls = self.getLotSize
                dynamic_capital = 185000.0 * (ls / 65.0)
                target_profit = self.smart_targets.get(self.currentDay.weekday(), 800) * (ls / 65.0)
            except:
                dynamic_capital = 185000.0
                target_profit = 800.0
            max_mtm_loss = -(dynamic_capital * 0.02)
            if not self.recovery_done and self.mtm < max_mtm_loss:
                self.square_off_all_positions(remark="MAX_LOSS_HIT")
                self.aborted_for_day = True
                self.abort_reason = "MAX_LOSS"
                return
            if self.mtm >= target_profit:
                self.square_off_all_positions(remark="PROFIT_TARGET_HIT")
                self.aborted_for_day = True
                self.abort_reason = "PROFIT"
                return
        if self.aborted_for_day and self.abort_reason == "LOSS" and not self.recovery_done:
            if self.candleTime >= datetime.time(12, 30):
                if self.day_open_price:
                    divergence = abs(spot_close - self.day_open_price) / self.day_open_price
                    if divergence > 0.010:
                        self.recovery_done = True
                        self.abort_reason = "LOSS_BLOCKED_RECOVERY"
                        return
                self.recovery_done = True
                self.sl_targets['rec_CE'] = spot_close * 1.01
                self.sl_targets['rec_PE'] = spot_close * 0.99
                spot_up = spot_close * 1.005
                spot_dn = spot_close * 0.995
                strike_diff = self.strikeDiff or 50
                ce_strike = round(spot_up / strike_diff) * strike_diff
                pe_strike = round(spot_dn / strike_diff) * strike_diff
                offset_ce = (ce_strike - spot_close) / strike_diff
                offset_pe = (spot_close - pe_strike) / strike_diff
                leg_c = self.add_managed_leg(side='sell', option_type='CE', lots=1, strike_selection={'strikeBy': 'moneyness', 'strikeVal': int(offset_ce) if offset_ce > 0 else 0, 'asof': 'None', 'roundoff': None}, exp={'expType': 'weekly', 'expNo': 0}, stop_loss={'isSL': False}, target={'isTarget': False}, trailing_stop_loss={'isTrailSL': False}, stop_loss_reentry={'isReEntry': False}, target_reentry={'isReEntry': False}, wait_trade={'isWT': False}, segment='OPT', square_off='this', leg_name='rec_CE', remark='0.5% Recovery CE')
                leg_p = self.add_managed_leg(side='sell', option_type='PE', lots=1, strike_selection={'strikeBy': 'moneyness', 'strikeVal': int(-offset_pe) if offset_pe < 0 else 0, 'asof': 'None', 'roundoff': None}, exp={'expType': 'weekly', 'expNo': 0}, stop_loss={'isSL': False}, target={'isTarget': False}, trailing_stop_loss={'isTrailSL': False}, stop_loss_reentry={'isReEntry': False}, target_reentry={'isReEntry': False}, wait_trade={'isWT': False}, segment='OPT', square_off='this', leg_name='rec_PE', remark='0.5% Recovery PE')
                self.actions_all['act_recovery']['legs'].extend([leg_c, leg_p])
        if self.recovery_done and not self.recovery_timed_exit_done:
            rec_ce = self.get_latest_leg("rec_CE")
            rec_pe = self.get_latest_leg("rec_PE")
            if rec_ce and rec_ce.is_open and spot_close >= self.sl_targets.get('rec_CE', float('inf')):
                rec_ce.exitTrade(remark="Spot SL Rec CE")
            if rec_pe and rec_pe.is_open and spot_close <= self.sl_targets.get('rec_PE', 0):
                rec_pe.exitTrade(remark="Spot SL Rec PE")

    def onEnd(self):
        pass
