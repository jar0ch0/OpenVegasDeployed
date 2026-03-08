import React from "react";
import {interpolate, useCurrentFrame} from "remotion";

type Horse = {
	name: string;
	odds: string;
	color: string;
	checkpoints: number[];
};

type LiveHorse = {
	horse: Horse;
	pos: number;
};

const COLORS = {
	black: "#050505",
	white: "#f3f3f3",
	greyDark: "#1a1a1a",
	greyMid: "#4a4a4a",
	greyLight: "#8a8a8a",
	cyan: "#5cb8e4",
};

const TOTAL_FRAMES = 480;
const PHASE_1_END = 72;
const PHASE_2_END = 180;
const PHASE_3_END = 300;
const PHASE_4_END = 390;
const HERO_HORSE = "Thunder Byte";

const HORSES: Horse[] = [
	{
		name: "Thunder Byte",
		odds: "5.3x",
		color: "#ef4444",
		checkpoints: [0, 6, 12, 17, 24, 29, 35, 43, 50, 58, 67, 74, 82, 88, 95],
	},
	{
		name: "Null Pointer",
		odds: "4.2x",
		color: "#3b82f6",
		checkpoints: [0, 8, 14, 20, 23, 28, 36, 41, 49, 56, 64, 72, 80, 89, 98],
	},
	{
		name: "Stack Overflow",
		odds: "3.1x",
		color: "#22c55e",
		checkpoints: [0, 5, 10, 18, 26, 33, 40, 45, 51, 60, 68, 76, 83, 90, 97],
	},
	{
		name: "Segfault Sally",
		odds: "3.7x",
		color: "#eab308",
		checkpoints: [0, 7, 13, 15, 21, 30, 38, 46, 53, 57, 63, 71, 79, 87, 96],
	},
	{
		name: "Cache Miss",
		odds: "4.8x",
		color: "#d946ef",
		checkpoints: [0, 4, 9, 14, 20, 26, 34, 40, 48, 55, 62, 69, 77, 86, 94],
	},
	{
		name: "Race Condition",
		odds: "5.3x",
		color: "#06b6d4",
		checkpoints: [0, 6, 11, 16, 19, 24, 31, 39, 47, 54, 61, 70, 78, 85, 93],
	},
	{
		name: "Deadlock Dan",
		odds: "3.1x",
		color: "#d4d4d8",
		checkpoints: [0, 5, 9, 14, 18, 24, 32, 39, 45, 52, 60, 68, 75, 84, 92],
	},
	{
		name: "Heap Corruption",
		odds: "4.3x",
		color: "#ef4444",
		checkpoints: [0, 4, 8, 13, 18, 22, 30, 37, 44, 50, 58, 65, 74, 82, 90],
	},
];

const getPositionAtProgress = (checkpoints: number[], progress: number): number => {
	const maxIdx = checkpoints.length - 1;
	if (maxIdx <= 0) {
		return 0;
	}
	const cpPos = progress * maxIdx;
	const lo = Math.floor(cpPos);
	const hi = Math.min(lo + 1, maxIdx);
	const t = cpPos - lo;
	return interpolate(t, [0, 1], [checkpoints[lo], checkpoints[hi]]);
};

const getLiveAtProgress = (progress: number): LiveHorse[] => {
	return HORSES.map((horse) => {
		const pos = getPositionAtProgress(horse.checkpoints, progress);
		return {horse, pos};
	});
};

const getLeaderNameAtFrame = (frame: number): string => {
	const safeFrame = Math.max(0, Math.min(frame, TOTAL_FRAMES - 1));
	const progress = safeFrame / (TOTAL_FRAMES - 1);
	const live = getLiveAtProgress(progress);
	return [...live].sort((a, b) => b.pos - a.pos)[0].horse.name;
};

const getPhaseLabel = (frame: number): string => {
	if (frame <= PHASE_1_END) {
		return "BOOT_SEQUENCE";
	}
	if (frame <= PHASE_2_END) {
		return "TRACK_REVEAL";
	}
	if (frame <= PHASE_3_END) {
		return "HERO_LOCK";
	}
	if (frame <= PHASE_4_END) {
		return "LEAD_PRESSURE";
	}
	return "FINISH_PROTOCOL";
};

export const HorseRace: React.FC = () => {
	const frame = useCurrentFrame();
	const progress = Math.min(frame / (TOTAL_FRAMES - 1), 1);

	const live = getLiveAtProgress(progress);
	const leaders = [...live].sort((a, b) => b.pos - a.pos).slice(0, 3);
	const hero = live.find((row) => row.horse.name === HERO_HORSE) ?? live[0];
	const currentLeader = leaders[0];
	const priorLeader = getLeaderNameAtFrame(frame - 8);
	const leadChanged = currentLeader.horse.name !== priorLeader;

	const cameraScale = interpolate(
		frame,
		[0, PHASE_1_END, PHASE_2_END, PHASE_3_END, PHASE_4_END, TOTAL_FRAMES - 1],
		[1.05, 1.03, 1.0, 1.08, 1.03, 1.0],
		{extrapolateLeft: "clamp", extrapolateRight: "clamp"},
	);

	const cameraX = interpolate(
		frame,
		[0, PHASE_2_END, PHASE_3_END, PHASE_4_END, TOTAL_FRAMES - 1],
		[20, 0, -56, -20, 0],
		{extrapolateLeft: "clamp", extrapolateRight: "clamp"},
	);
	const heroBias = interpolate(hero.pos, [0, 100], [75, -85], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const heroLockWeight = interpolate(frame, [PHASE_2_END, PHASE_3_END], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const cameraY = interpolate(frame, [0, PHASE_1_END, PHASE_3_END, TOTAL_FRAMES - 1], [0, -8, -20, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	const bootOpacity = interpolate(frame, [0, 24, 56, PHASE_1_END], [1, 1, 0.4, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const leadPulse = interpolate(frame, [290, 330, 365, PHASE_4_END], [0, 1, 0.8, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const finishCardOpacity = interpolate(frame, [PHASE_4_END, 430, TOTAL_FRAMES - 1], [0, 0.45, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const finishCardTranslate = interpolate(frame, [PHASE_4_END, TOTAL_FRAMES - 1], [32, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});

	return (
		<div
			style={{
				width: "100%",
				height: "100%",
				background: COLORS.black,
				color: COLORS.white,
				fontFamily: '"JetBrains Mono", "IBM Plex Mono", monospace',
				position: "relative",
				overflow: "hidden",
			}}
		>
			<div
				style={{
					position: "absolute",
					inset: 0,
					background:
						"radial-gradient(circle at 72% 12%, rgba(92,184,228,0.08), transparent 28%), radial-gradient(circle at 10% 86%, rgba(255,255,255,0.025), transparent 34%)",
				}}
			/>

			<div
				style={{
					position: "absolute",
					inset: 0,
					background:
						"repeating-linear-gradient(to right, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.02) 1px, transparent 1px, transparent 128px), repeating-linear-gradient(to bottom, rgba(255,255,255,0.01) 0px, rgba(255,255,255,0.01) 1px, transparent 1px, transparent 72px)",
					opacity: 0.28,
					transform: `translateY(${(frame % 9) - 4}px)`,
				}}
			/>

			<div
				style={{
					position: "absolute",
					top: 0,
					left: 0,
					right: 0,
					height: 22,
					background:
						"repeating-linear-gradient(to bottom, rgba(255,255,255,0.05) 0px, rgba(255,255,255,0.05) 1px, transparent 1px, transparent 3px)",
					opacity: 0.1,
				}}
			/>

			<div
				style={{
					position: "absolute",
					inset: 0,
					padding: "34px 42px 32px 42px",
					boxSizing: "border-box",
					transform: `translate(${cameraX + heroBias * heroLockWeight}px, ${cameraY}px) scale(${cameraScale})`,
					transformOrigin: "center center",
					display: "grid",
					gridTemplateRows: "auto auto 1fr auto",
					gap: 14,
				}}
			>
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						alignItems: "center",
						borderBottom: `1px solid ${COLORS.greyDark}`,
						paddingBottom: 14,
						fontSize: 12,
						letterSpacing: "0.12em",
						textTransform: "uppercase",
						color: COLORS.greyLight,
					}}
				>
					<span>★ OPENVEGAS DERBY ★</span>
					<span>{getPhaseLabel(frame)}</span>
					<span>Frame {frame.toString().padStart(3, "0")}</span>
				</div>

				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						fontSize: 11,
						letterSpacing: "0.11em",
						textTransform: "uppercase",
						color: COLORS.greyMid,
					}}
				>
					<span style={{color: COLORS.cyan}}>Directory: OpenVegas_RaceCore_V2</span>
					<span>Session Mode: Wagered_Compute</span>
					<span>Track Telemetry: Active</span>
				</div>

				<div style={{display: "grid", gridTemplateColumns: "1fr 376px", gap: 18, flex: 1}}>
					<div
						style={{
							border: `1px solid ${COLORS.greyDark}`,
							background: "rgba(255,255,255,0.01)",
							padding: 0,
						}}
					>
						<div
							style={{
								display: "grid",
								gridTemplateColumns: "220px 1fr 84px",
							}}
						>
							{live.map(({horse, pos}, idx) => {
							const leftPercent = 100 - pos;
							const isLeader = horse.name === currentLeader.horse.name;
							const isHero = horse.name === HERO_HORSE;
							return (
								<React.Fragment key={horse.name}>
									<div
										style={{
											height: 87,
											borderBottom: idx < live.length - 1 ? `1px solid ${COLORS.greyDark}` : "none",
											padding: "16px 12px 0 14px",
											boxSizing: "border-box",
											display: "flex",
											alignItems: "flex-start",
											gap: 10,
											fontSize: 40,
										}}
									>
										<span
											style={{
												color: horse.color,
												fontWeight: 700,
												fontSize: 39,
												lineHeight: 1,
											}}
										>
											#{idx + 1}
										</span>
										<span
											style={{
												color: isHero ? COLORS.white : "#c9c9c9",
												fontSize: 40,
												lineHeight: 1,
												letterSpacing: "0.01em",
											}}
										>
											{horse.name.slice(0, 10)}
										</span>
									</div>
									<div
										style={{
											height: 87,
											borderLeft: `1px solid ${COLORS.greyLight}`,
											borderRight: `1px solid ${COLORS.greyDark}`,
											borderBottom: idx < live.length - 1 ? `1px solid ${COLORS.greyDark}` : "none",
											position: "relative",
											overflow: "hidden",
											background:
												"repeating-linear-gradient(to bottom, rgba(255,255,255,0.018) 0px, rgba(255,255,255,0.018) 1px, transparent 1px, transparent 2px)",
										}}
									>
										<div
											style={{
												position: "absolute",
												left: 2,
												top: 0,
												bottom: 0,
												width: 3,
												background: COLORS.greyLight,
												opacity: 0.95,
											}}
										/>
										<div
											style={{
												position: "absolute",
												right: 0,
												top: 0,
												bottom: 0,
												width: `${pos}%`,
												background: horse.color,
												opacity: 0.86,
											}}
										/>
										<div
											style={{
												position: "absolute",
												left: `calc(${leftPercent}% - 16px)`,
												top: "50%",
												transform: "translateY(-50%)",
												display: "flex",
												alignItems: "center",
												gap: 0,
												fontSize: 33,
												lineHeight: 1,
												textShadow: isLeader ? `0 0 14px ${horse.color}` : "none",
											}}
										>
											<span style={{color: COLORS.white}}>&lt;</span>
											<span style={{color: horse.color}}>𓃗</span>
										</div>
										{isLeader ? (
											<div
												style={{
													position: "absolute",
													inset: 0,
													border: `1px solid ${COLORS.cyan}`,
													opacity: 0.55,
												}}
											/>
										) : null}
									</div>
									<div
										style={{
											height: 87,
											borderBottom: idx < live.length - 1 ? `1px solid ${COLORS.greyDark}` : "none",
											display: "flex",
											alignItems: "center",
											justifyContent: "flex-end",
											paddingRight: 10,
											fontSize: 40,
											lineHeight: 1,
											color: "#8f8f8f",
										}}
									>
										{horse.odds}
									</div>
								</React.Fragment>
							);
						})}
						</div>
					</div>

					<div
						style={{
							border: `1px solid ${COLORS.greyDark}`,
							background: "rgba(255,255,255,0.016)",
							padding: 16,
							display: "flex",
							flexDirection: "column",
							gap: 12,
						}}
					>
						<div
							style={{
								fontSize: 11,
								letterSpacing: "0.12em",
								textTransform: "uppercase",
								color: COLORS.greyMid,
							}}
						>
							Live Leaders
						</div>

						{leaders.map(({horse, pos}, idx) => (
							<div
								key={horse.name}
								style={{
									display: "flex",
									justifyContent: "space-between",
									alignItems: "center",
									borderTop: `1px solid ${COLORS.greyDark}`,
									paddingTop: 10,
									fontSize: 11,
									letterSpacing: "0.08em",
									textTransform: "uppercase",
								}}
							>
								<span style={{color: idx === 0 ? COLORS.cyan : COLORS.white}}>
									#{idx + 1} {horse.name}
								</span>
								<span style={{color: COLORS.greyLight}}>{pos.toFixed(1)}%</span>
							</div>
						))}

						<div
							style={{
								marginTop: 6,
								borderTop: `1px solid ${COLORS.greyDark}`,
								paddingTop: 10,
								fontSize: 10,
								letterSpacing: "0.1em",
								textTransform: "uppercase",
								lineHeight: 1.8,
								color: COLORS.greyLight,
							}}
						>
							<div>Model: Horse_V2_Balanced</div>
							<div>Session Mode: Wagered_Compute</div>
							<div>Track Telemetry: Active</div>
							<div>Odds Drift: +11.8%</div>
							<div>Latency: &lt;15ms</div>
							<div>FPS: 30</div>
						</div>

						<div
							style={{
								marginTop: "auto",
								borderTop: `1px solid ${COLORS.greyDark}`,
								paddingTop: 12,
								fontSize: 12,
								letterSpacing: "0.12em",
								textTransform: "uppercase",
								color: COLORS.cyan,
							}}
						>
							Wager Tokens | Route Compute
						</div>
					</div>
				</div>

				<div
					style={{
					display: "grid",
					gridTemplateColumns: "repeat(4, 1fr)",
					gap: 12,
					borderTop: `1px solid ${COLORS.greyDark}`,
					paddingTop: 10,
					fontSize: 10,
					letterSpacing: "0.1em",
					textTransform: "uppercase",
						color: COLORS.greyMid,
					}}
				>
					<div>Node_Alpha: US-EAST Active</div>
					<div>Node_Bravo: EU-CENTRAL Active</div>
					<div>Node_Charlie: AP-SOUTHEAST Queue</div>
					<div style={{color: COLORS.cyan}}>System Health: Optimized</div>
				</div>
			</div>

			<div
				style={{
					position: "absolute",
					inset: 0,
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
					background: `rgba(0, 0, 0, ${0.88 * bootOpacity})`,
					opacity: bootOpacity,
					pointerEvents: "none",
				}}
			>
				<div
					style={{
						border: `1px solid ${COLORS.greyDark}`,
						padding: "18px 26px",
						background: "rgba(255,255,255,0.02)",
						textTransform: "uppercase",
						letterSpacing: "0.11em",
						lineHeight: 1.8,
					}}
				>
					<div style={{color: COLORS.white, fontSize: 15}}>OpenVegas // RaceCore Init</div>
					<div style={{color: COLORS.greyLight, fontSize: 11}}>Directory: OpenVegas_RaceCore_V2</div>
					<div style={{color: COLORS.cyan, fontSize: 11}}>Session Mode: Wagered_Compute</div>
				</div>
			</div>

			<div
				style={{
					position: "absolute",
					top: 88,
					right: 46,
					border: `1px solid ${COLORS.cyan}`,
					background: "rgba(92,184,228,0.08)",
					padding: "10px 14px",
					fontSize: 11,
					letterSpacing: "0.12em",
					textTransform: "uppercase",
					color: COLORS.cyan,
					opacity: (leadChanged ? 1 : 0.6) * leadPulse,
				}}
			>
				Lead Change Detected
			</div>

			<div
				style={{
					position: "absolute",
					right: 40,
					bottom: 34,
					border: `1px solid ${COLORS.greyDark}`,
					padding: "12px 16px",
					background: "rgba(0,0,0,0.72)",
					fontSize: 11,
					letterSpacing: "0.11em",
					textTransform: "uppercase",
					lineHeight: 1.8,
					color: COLORS.white,
					opacity: finishCardOpacity,
					transform: `translateY(${finishCardTranslate}px)`,
				}}
			>
				<div style={{color: COLORS.greyLight}}>Finish Protocol</div>
				<div style={{color: COLORS.cyan}}>Winner: {leaders[0].horse.name}</div>
				<div style={{color: COLORS.white}}>Deploy Risk // Wager Tokens</div>
			</div>
		</div>
	);
};
