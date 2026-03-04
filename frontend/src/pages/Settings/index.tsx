import { Typography, Tabs } from 'antd';
import { SettingOutlined, PrinterOutlined, ApiOutlined } from '@ant-design/icons';
import ModelConfigPanel from './ModelConfigPanel.tsx';
import PrintConfigPanel from './PrintConfigPanel.tsx';
import SystemConfigPanel from './SystemConfigPanel.tsx';

const { Title } = Typography;

export default function Settings() {
  return (
    <div>
      <Title level={3}>设置</Title>
      <Tabs
        defaultActiveKey="models"
        items={[
          {
            key: 'models',
            label: (
              <span>
                <SettingOutlined /> 模型配置
              </span>
            ),
            children: <ModelConfigPanel />,
          },
          {
            key: 'print',
            label: (
              <span>
                <PrinterOutlined /> 打印配置
              </span>
            ),
            children: <PrintConfigPanel />,
          },
          {
            key: 'system',
            label: (
              <span>
                <ApiOutlined /> 系统配置
              </span>
            ),
            children: <SystemConfigPanel />,
          },
        ]}
      />
    </div>
  );
}
