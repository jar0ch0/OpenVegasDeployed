import "./index.css";
import React from "react";
import {Composition} from "remotion";
import {MyComposition} from "./Composition";

export const RemotionRoot: React.FC = () => {
	return (
		<>
			<Composition
				id="OpenVegasHorseRace"
				component={MyComposition}
				durationInFrames={480}
				fps={30}
				width={1920}
				height={1080}
			/>
		</>
	);
};
