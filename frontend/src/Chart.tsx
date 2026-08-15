import ReactEChartsCore from "echarts-for-react/esm/core";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent, CanvasRenderer]);

export default function IntelligenceChart({ option }: { option: object }) {
  if (typeof window !== "undefined" && window.navigator?.userAgent?.includes("jsdom")) {
    return <div className="echarts-test-mock" data-testid="intelligence-chart" style={{ height: "100%" }} />;
  }

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      theme="dark"
      notMerge
      lazyUpdate
      style={{ height: "100%" }}
    />
  );
}
