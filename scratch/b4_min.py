#!/usr/bin/env python
_j='be_locked'
_i='max_rolls'
_h='peak_mtm'
_g='%Y-%m-%d'
_f='SENSEX'
_e='STRIKE_INTERVAL'
_d='LOT_SIZE'
_c='recovery_timed_exit_done'
_b='FINNIFTY'
_a='NIFTY'
_Z='day_open_price'
_Y='BANKNIFTY'
_X='ref_spot'
_W='SELL'
_V='MIS'
_U='MARKET'
_T='rolls_done'
_S='entry_done'
_R='recovery_done'
_Q=False
_P='abort_reason'
_O='aborted_for_day'
_N=.0
_M='stop_loss_spot'
_L=None
_K=True
_J='realized_pnl'
_I='last_price'
_H='is_open'
_G='symbol'
_F='qty'
_E='rec_pe_leg'
_D='rec_ce_leg'
_C='pe_leg'
_B='entry_price'
_A='ce_leg'
import os,sys,time,json,traceback
from datetime import datetime,timedelta,timezone,time as time_obj
import pandas as pd
from openalgo import api
STRATEGY_NAME=os.getenv('STRATEGY_NAME','Bot4_Short_Straddle')
UNDERLYING=os.getenv('UNDERLYING',_a)
EXCHANGE=os.getenv('OPENALGO_STRATEGY_EXCHANGE',os.getenv('EXCHANGE','NSE_INDEX'))
OPTION_EXCHANGE=os.getenv('OPTION_EXCHANGE','NFO')
EXECUTION_MODE='options_selling'
def _get_default_param(param_name,underlying):
	if param_name==_d:
		if underlying==_a:return 65
		elif underlying==_Y:return 30
		elif underlying==_b:return 60
		elif underlying=='MIDCPNIFTY':return 120
		return 30
	elif param_name==_e:
		if underlying==_a:return 50
		elif underlying==_Y:return 100
		elif underlying==_b:return 100
		return 100
	return 0
LOT_SIZE=int(os.getenv(_d,str(_get_default_param(_d,UNDERLYING))))
LOT_MULTIPLIER=int(os.getenv('LOT_MULTIPLIER','1'))
STRIKE_INTERVAL=int(os.getenv(_e,str(_get_default_param(_e,UNDERLYING))))
def get_deployed_capital(symbol,qty):margin_per_lot=160000 if symbol==_Y else 100000 if symbol==_f else 185000 if symbol==_a else 160000;base_lot_size=30 if symbol==_Y else 10 if symbol==_f else 40 if symbol==_b else 65;return max(margin_per_lot,qty/base_lot_size*margin_per_lot)
FALLBACK_CAPITAL=float(os.getenv('CAPITAL','800000.0'))
SPOT_SL_PCT=float(os.getenv('SPOT_SL_PCT','0.01'))
PROFIT_TARGET_PER_LOT=float(os.getenv('PROFIT_TARGET_PER_LOT','1600'))
MAX_MTM_LOSS_PCT=float(os.getenv('MAX_MTM_LOSS_PCT','0.02'))
GAP_ABORT_PCT=float(os.getenv('GAP_ABORT_PCT','0.005'))
ENTRY_TIME=os.getenv('ENTRY_TIME','09:30')
HARD_SQUARE_OFF=os.getenv('HARD_SQUARE_OFF','15:15')
PAPER_MODE=os.getenv('PAPER_MODE','true').lower()=='true'
STATE_FILE=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..','bot4_strategy_state.json'))
IST=timezone(timedelta(hours=5,minutes=30))
def get_ist_now():return datetime.now(IST)
def check_time_windows():
	now_time=get_ist_now().time()
	def to_time(t_str):h,m=map(int,t_str.split(':'));return time_obj(h,m)
	entry=to_time(ENTRY_TIME);square_off=to_time(HARD_SQUARE_OFF);is_entry_minute=(now_time.hour==entry.hour and now_time.minute>=entry.minute)and now_time<square_off;past_square_off=now_time>=square_off;return is_entry_minute,past_square_off
def load_state():
	A='date'
	if os.path.exists(STATE_FILE):
		try:
			with open(STATE_FILE,'r')as f:
				state=json.load(f);state_date=state.get(A)
				if state_date==get_ist_now().strftime(_g):return state
		except Exception as e:print(f"[WARN] Failed to load state file: {e}. Starting fresh.")
	return{A:get_ist_now().strftime(_g),_S:_Q,_O:_Q,_h:_N,_j:_Q,_A:_L,_C:_L,_T:0,_i:1,_J:_N,_P:_L,_R:_Q,_c:_Q,_D:_L,_E:_L,_Z:_L}
def save_state(state):
	state['last_heartbeat']=datetime.now(timezone.utc).timestamp();temp_file=f"{STATE_FILE}.tmp"
	try:
		with open(temp_file,'w')as f:json.dump(state,f,indent=4)
		success=_Q
		for attempt in range(6):
			try:os.replace(temp_file,STATE_FILE);success=_K;break
			except PermissionError:time.sleep(.02*2**attempt)
		if not success:
			print(f"[{datetime.now()}] [WARN] Dropping state save. OS locked file for too long.")
			if os.path.exists(temp_file):
				try:os.remove(temp_file)
				except:pass
	except Exception as e:print(f"Error saving state atomically: {e}")
def resolve_atm_strike(spot):return round(spot/STRIKE_INTERVAL)*STRIKE_INTERVAL
def get_nearest_expiry(client):
	A='expiry'
	try:
		sym_info=client.get_symbols(exchange=OPTION_EXCHANGE,underlying=UNDERLYING);df=pd.DataFrame(sym_info)
		if df.empty:return _L,_L
		df[A]=pd.to_datetime(df[A]);nearest=df[df[A]>=pd.Timestamp(get_ist_now().date())].sort_values(A).iloc[0];return nearest[A].strftime('%y%b').upper(),nearest[A].strftime(_g)
	except Exception as e:print(f"Error fetching expiry: {e}");return _L,_L
def execute_straddle(client,spot,expiry_formatted,qty):
	atm_strike=resolve_atm_strike(spot);ce_sym=f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE";pe_sym=f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE";print(f"[{datetime.now()}] Executing 09:30 Straddle: SELL {ce_sym} & SELL {pe_sym}")
	try:
		if not PAPER_MODE:client.placeorder(strategy=STRATEGY_NAME,symbol=ce_sym,action=_W,exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=qty);client.placeorder(strategy=STRATEGY_NAME,symbol=pe_sym,action=_W,exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=qty)
		time.sleep(1);ce_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=ce_sym).get(_I,spot*.01);pe_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=pe_sym).get(_I,spot*.01);return{_G:ce_sym,_B:ce_ltp,_F:qty,_H:_K,_M:spot*(1+SPOT_SL_PCT),_X:spot},{_G:pe_sym,_B:pe_ltp,_F:qty,_H:_K,_M:spot*(1-SPOT_SL_PCT),_X:spot}
	except Exception as e:print(f"Execution failed: {e}");return _L,_L
def execute_strangle(client,spot,expiry_formatted,qty,width_pct=.005):
	ce_strike=round(spot*(1+width_pct)/STRIKE_INTERVAL)*STRIKE_INTERVAL;pe_strike=round(spot*(1-width_pct)/STRIKE_INTERVAL)*STRIKE_INTERVAL;ce_sym=f"{UNDERLYING}{expiry_formatted}{int(ce_strike)}CE";pe_sym=f"{UNDERLYING}{expiry_formatted}{int(pe_strike)}PE";print(f"[{datetime.now()}] Executing 12:30 Recovery Strangle: SELL {ce_sym} & SELL {pe_sym}")
	try:
		if not PAPER_MODE:client.placeorder(strategy=STRATEGY_NAME,symbol=ce_sym,action=_W,exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=qty);client.placeorder(strategy=STRATEGY_NAME,symbol=pe_sym,action=_W,exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=qty)
		time.sleep(1);ce_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=ce_sym).get(_I,spot*.01);pe_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=pe_sym).get(_I,spot*.01);return{_G:ce_sym,_B:ce_ltp,_F:qty,_H:_K,_M:spot*1.01,_X:spot},{_G:pe_sym,_B:pe_ltp,_F:qty,_H:_K,_M:spot*.99,_X:spot}
	except Exception as e:print(f"Recovery Execution failed: {e}");return _L,_L
def close_leg(client,leg):
	print(f"[{datetime.now()}] Closing leg: {leg[_G]}")
	if not PAPER_MODE:
		try:client.placeorder(strategy=STRATEGY_NAME,symbol=leg[_G],action='BUY',exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=leg[_F])
		except Exception as e:print(f"Error closing leg: {e}")
		if'hedge_symbol'in leg:0
	leg[_H]=_Q;return leg
def main():
	A='LOSS';print(f"[{datetime.now()}] Initialize Bot 4 (09:30 Short Straddle with Smart Adjustments)");api_key=os.getenv('OPENALGO_API_KEY');client=api(api_key=api_key,host='http://127.0.0.1:5000');state=load_state();print(f"[{datetime.now()}] State loaded: {state}")
	if state.get(_S)and not state.get(_O):
		try:
			q=client.get_quotes(exchange=EXCHANGE,symbol=UNDERLYING);reboot_spot=q.get(_I,0)
			if reboot_spot>0:
				print(f"[{datetime.now()}] REBOOT RECONCILIATION: Spot={reboot_spot}")
				for leg_key in[_A,_C,_D,_E]:
					leg=state.get(leg_key)
					if leg and leg.get(_H):
						if reboot_spot>=leg[_M]and'CE'in leg[_G]or reboot_spot<=leg[_M]and'PE'in leg[_G]:print(f"[CRITICAL] DOWNTIME GAP ABORT: {leg[_G]} SL breached during downtime!");leg_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=leg[_G]).get(_I,leg[_B]);state[_J]=state.get(_J,_N)+(leg[_B]-leg_ltp)*leg[_F];close_leg(client,leg);state[_O]=_K;state[_P]='DOWNTIME_GAP_ABORT'
				save_state(state)
		except Exception as e:print(f"Reboot gap check failed: {e}")
	while _K:
		try:
			now_ist=get_ist_now();is_entry_minute,past_square_off=check_time_windows()
			if past_square_off or state.get(_O,_Q)and not(state.get(_P)==A and not state.get(_R,_Q)):
				if state[_A]and state[_A][_H]:ce_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_A][_G]).get(_I,state[_A][_B]);state[_J]=state.get(_J,_N)+(state[_A][_B]-ce_ltp_close)*state[_A][_F];close_leg(client,state[_A])
				if state[_C]and state[_C][_H]:pe_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_C][_G]).get(_I,state[_C][_B]);state[_J]=state.get(_J,_N)+(state[_C][_B]-pe_ltp_close)*state[_C][_F];close_leg(client,state[_C])
				if state.get(_D)and state[_D][_H]:r_ce_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_D][_G]).get(_I,state[_D][_B]);state[_J]=state.get(_J,_N)+(state[_D][_B]-r_ce_ltp)*state[_D][_F];close_leg(client,state[_D])
				if state.get(_E)and state[_E][_H]:r_pe_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_E][_G]).get(_I,state[_E][_B]);state[_J]=state.get(_J,_N)+(state[_E][_B]-r_pe_ltp)*state[_E][_F];close_leg(client,state[_E])
				state[_S]=_K;save_state(state)
				if past_square_off:print(f"[{datetime.now()}] EOD Square Off Complete. Exiting loop.");time.sleep(60)
				else:time.sleep(10)
				continue
			if is_entry_minute and not state[_S]:
				spot_data=client.get_quotes(exchange=EXCHANGE,symbol=UNDERLYING);spot_price=spot_data.get(_I);prev_close=spot_data.get('prev_close_price')
				if spot_price and state.get(_Z)is _L:state[_Z]=spot_price
				if spot_price and prev_close and prev_close>0:
					gap_pct=abs(spot_price-prev_close)/prev_close
					if gap_pct>GAP_ABORT_PCT:print(f"[{datetime.now()}] ABORTING: Gap {gap_pct*100:.2f}% > threshold {GAP_ABORT_PCT*100:.2f}%");state[_O]=_K;state[_P]='GAP';state[_S]=_K;save_state(state);continue
				elif not spot_price:print(f"[{datetime.now()}] WARNING: Could not fetch spot price. Skipping entry attempt.");continue
				expiry_fmt,_=get_nearest_expiry(client)
				if expiry_fmt:
					final_qty=LOT_SIZE*LOT_MULTIPLIER;ce_leg,pe_leg=execute_straddle(client,spot_price,expiry_fmt,final_qty)
					if ce_leg and pe_leg:state[_A]=ce_leg;state[_C]=pe_leg;state[_S]=_K;state[_j]=_Q;save_state(state)
			if state[_S]:
				if state.get(_O)and state.get(_P)==A and not state.get(_R):
					if now_ist.hour==12 and now_ist.minute>=30 or now_ist.hour>=13:
						spot_data=client.get_quotes(exchange=EXCHANGE,symbol=UNDERLYING);spot_price=spot_data.get(_I);expiry_fmt,_=get_nearest_expiry(client)
						if spot_price and expiry_fmt:
							divergence=abs(spot_price-state.get(_Z,spot_price))/state.get(_Z,spot_price)
							if divergence>.01:print(f"[{datetime.now()}] [RECOVERY ABORTED] Extreme Trend Detected (Divergence: {divergence*100:.2f}% > 1.0%)");state[_R]=_K;state[_P]='LOSS_BLOCKED_RECOVERY';save_state(state)
							else:
								deployed_qty=state.get(_A,{}).get(_F)or LOT_SIZE*LOT_MULTIPLIER;r_ce_leg,r_pe_leg=execute_strangle(client,spot_price,expiry_fmt,deployed_qty,width_pct=.005)
								if r_ce_leg and r_pe_leg:state[_D]=r_ce_leg;state[_E]=r_pe_leg;state[_R]=_K;save_state(state)
				if not state.get(_O)or state.get(_R):current_mtm=state.get(_J,_N);spot_data=client.get_quotes(exchange=EXCHANGE,symbol=UNDERLYING);current_spot=spot_data.get(_I)
				deployed_qty=state.get(_A,{}).get(_F)or state.get(_C,{}).get(_F)or LOT_SIZE*LOT_MULTIPLIER;dynamic_capital=get_deployed_capital(UNDERLYING,deployed_qty);base_lot_size=30 if UNDERLYING==_Y else 10 if UNDERLYING==_f else 40 if UNDERLYING==_b else 65;day_of_week=get_ist_now().weekday()
				if day_of_week==1:smart_target=300
				elif day_of_week==0:smart_target=500
				else:smart_target=800
				target_profit=max(1,deployed_qty/base_lot_size)*smart_target
				if state[_A]and state[_A][_H]:
					ce_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_A][_G]).get(_I)
					if ce_ltp:
						current_mtm+=(state[_A][_B]-ce_ltp)*state[_A][_F]
						if current_spot and current_spot>=state[_A][_M]:
							print(f"[{datetime.now()}] CE STOP LOSS HIT! Spot {current_spot} >= {state[_A][_M]}");state[_J]=state.get(_J,_N)+(state[_A][_B]-ce_ltp)*state[_A][_F];close_leg(client,state[_A])
							if state.get(_T,0)<state.get(_i,1):
								if state[_C]and state[_C][_H]:pe_ltp_for_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_C][_G]).get(_I,state[_C][_B]);state[_J]+=(state[_C][_B]-pe_ltp_for_close)*state[_C][_F];close_leg(client,state[_C])
								if current_spot and expiry_fmt:
									print(f"[{datetime.now()}] Market Trending UP. Rolling PE UP to ATM...");atm_strike=resolve_atm_strike(current_spot);new_pe_sym=f"{UNDERLYING}{expiry_fmt}{int(atm_strike)}PE";qty=state[_C][_F]
									if not PAPER_MODE:client.placeorder(strategy=STRATEGY_NAME,symbol=new_pe_sym,action=_W,exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=qty)
									time.sleep(1);new_pe_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=new_pe_sym).get(_I,current_spot*.01);state[_C]={_G:new_pe_sym,_B:new_pe_ltp,_F:qty,_H:_K,_M:current_spot*(1-SPOT_SL_PCT),_X:current_spot};state[_T]=state.get(_T,0)+1
							elif not state.get(_C,{}).get(_H):print(f"[{datetime.now()}] Both legs SL hit and max rolls reached. Aborting for day (Armed for Recovery).");state[_O]=_K;state[_P]=A
							save_state(state)
				if state[_C]and state[_C][_H]:
					pe_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_C][_G]).get(_I)
					if pe_ltp:
						current_mtm+=(state[_C][_B]-pe_ltp)*state[_C][_F]
						if current_spot and current_spot<=state[_C][_M]:
							print(f"[{datetime.now()}] PE STOP LOSS HIT! Spot {current_spot} <= {state[_C][_M]}");state[_J]=state.get(_J,_N)+(state[_C][_B]-pe_ltp)*state[_C][_F];close_leg(client,state[_C])
							if state.get(_T,0)<state.get(_i,1):
								if state[_A]and state[_A][_H]:ce_ltp_for_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_A][_G]).get(_I,state[_A][_B]);state[_J]+=(state[_A][_B]-ce_ltp_for_close)*state[_A][_F];close_leg(client,state[_A])
								if current_spot and expiry_fmt:
									print(f"[{datetime.now()}] Market Trending DOWN. Rolling CE DOWN to ATM...");atm_strike=resolve_atm_strike(current_spot);new_ce_sym=f"{UNDERLYING}{expiry_fmt}{int(atm_strike)}CE";qty=state[_A][_F]
									if not PAPER_MODE:client.placeorder(strategy=STRATEGY_NAME,symbol=new_ce_sym,action=_W,exchange=OPTION_EXCHANGE,price_type=_U,product=_V,quantity=qty)
									time.sleep(1);new_ce_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=new_ce_sym).get(_I,current_spot*.01);state[_A]={_G:new_ce_sym,_B:new_ce_ltp,_F:qty,_H:_K,_M:current_spot*(1+SPOT_SL_PCT),_X:current_spot};state[_T]=state.get(_T,0)+1
							elif not state.get(_A,{}).get(_H):print(f"[{datetime.now()}] Both legs SL hit and max rolls reached. Aborting for day (Armed for Recovery).");state[_O]=_K;state[_P]=A
							save_state(state)
				if state.get(_D)and state[_D][_H]:
					r_ce_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_D][_G]).get(_I)
					if r_ce_ltp:
						current_mtm+=(state[_D][_B]-r_ce_ltp)*state[_D][_F]
						if current_spot and current_spot>=state[_D][_M]:print(f"[{datetime.now()}] REC CE STOP LOSS HIT! Spot {current_spot} >= {state[_D][_M]}");state[_J]+=(state[_D][_B]-r_ce_ltp)*state[_D][_F];close_leg(client,state[_D]);save_state(state)
				if state.get(_E)and state[_E][_H]:
					r_pe_ltp=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_E][_G]).get(_I)
					if r_pe_ltp:
						current_mtm+=(state[_E][_B]-r_pe_ltp)*state[_E][_F]
						if current_spot and current_spot<=state[_E][_M]:print(f"[{datetime.now()}] REC PE STOP LOSS HIT! Spot {current_spot} <= {state[_E][_M]}");state[_J]+=(state[_E][_B]-r_pe_ltp)*state[_E][_F];close_leg(client,state[_E]);save_state(state)
				if now_ist.hour>=14 and not state.get(_c)and state.get(_R)and(state.get(_D,{}).get(_H)or state.get(_E,{}).get(_H)):
					rec_mtm=_N
					if state.get(_D)and state[_D][_H]:
						r_ce_ltp_chk=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_D][_G]).get(_I)
						if r_ce_ltp_chk:rec_mtm+=(state[_D][_B]-r_ce_ltp_chk)*state[_D][_F]
					if state.get(_E)and state[_E][_H]:
						r_pe_ltp_chk=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_E][_G]).get(_I)
						if r_pe_ltp_chk:rec_mtm+=(state[_E][_B]-r_pe_ltp_chk)*state[_E][_F]
					if rec_mtm<0:
						print(f"[{datetime.now()}] [STRATEGY A] Recovery trade in loss (Rs.{rec_mtm:.0f}) at 14:00 — cutting flat to prevent Gamma blowup.")
						if state.get(_D)and state[_D][_H]:r_ce_ltp_cut=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_D][_G]).get(_I,state[_D][_B]);state[_J]=state.get(_J,_N)+(state[_D][_B]-r_ce_ltp_cut)*state[_D][_F];close_leg(client,state[_D])
						if state.get(_E)and state[_E][_H]:r_pe_ltp_cut=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_E][_G]).get(_I,state[_E][_B]);state[_J]=state.get(_J,_N)+(state[_E][_B]-r_pe_ltp_cut)*state[_E][_F];close_leg(client,state[_E])
						state[_c]=_K;state[_O]=_K;state[_P]='RECOVERY_TIMED_EXIT';save_state(state);continue
					else:state[_c]=_K;save_state(state)
				if current_mtm>state.get(_h,0):state[_h]=current_mtm
				if current_mtm>=target_profit:
					print(f"[{datetime.now()}] PROFIT TARGET HIT! MTM={current_mtm:.0f} (Target: {target_profit:.0f})")
					if state.get(_A)and state[_A][_H]:ce_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_A][_G]).get(_I,state[_A][_B]);state[_J]+=(state[_A][_B]-ce_ltp_close)*state[_A][_F];close_leg(client,state[_A])
					if state.get(_C)and state[_C][_H]:pe_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_C][_G]).get(_I,state[_C][_B]);state[_J]+=(state[_C][_B]-pe_ltp_close)*state[_C][_F];close_leg(client,state[_C])
					if state.get(_D)and state[_D][_H]:r_ce_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_D][_G]).get(_I,state[_D][_B]);state[_J]+=(state[_D][_B]-r_ce_ltp_close)*state[_D][_F];close_leg(client,state[_D])
					if state.get(_E)and state[_E][_H]:r_pe_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_E][_G]).get(_I,state[_E][_B]);state[_J]+=(state[_E][_B]-r_pe_ltp_close)*state[_E][_F];close_leg(client,state[_E])
					state[_O]=_K;state[_P]='PROFIT';save_state(state);continue
				if not state.get(_R):
					if current_mtm<-(dynamic_capital*MAX_MTM_LOSS_PCT):
						print(f"[{datetime.now()}] MAX LOSS HIT! MTM={current_mtm:.0f}, Cap={-(dynamic_capital*MAX_MTM_LOSS_PCT):.0f}")
						if state.get(_A)and state[_A][_H]:ce_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_A][_G]).get(_I,state[_A][_B]);state[_J]+=(state[_A][_B]-ce_ltp_close)*state[_A][_F];close_leg(client,state[_A])
						if state.get(_C)and state[_C][_H]:pe_ltp_close=client.get_quotes(exchange=OPTION_EXCHANGE,symbol=state[_C][_G]).get(_I,state[_C][_B]);state[_J]+=(state[_C][_B]-pe_ltp_close)*state[_C][_F];close_leg(client,state[_C])
						state[_O]=_K;state[_P]='MAX_LOSS';save_state(state);continue
			save_state(state);time.sleep(2.5)
		except Exception as e:print(f"[{datetime.now()}] Exception in strategy loop: {e}");traceback.print_exc();time.sleep(5)
def check_signals(df_slice,current_position=_L):
	A='HOLD'
	if len(df_slice)<1:return A
	last_idx=df_slice.index[-1]
	if hasattr(last_idx,'hour'):h,m=last_idx.hour,last_idx.minute
	else:
		try:dt=pd.Timestamp(last_idx);h,m=dt.hour,dt.minute
		except Exception:return A
	if h==9 and m==30 and current_position is _L:return'SHORT_STRADDLE'
	return A
if __name__=='__main__':main()