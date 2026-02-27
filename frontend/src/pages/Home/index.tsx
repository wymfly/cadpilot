import { Typography, Card, Row, Col } from 'antd';
import {
  ExperimentOutlined,
  BulbOutlined,
  AppstoreOutlined,
  BookOutlined,
  BarChartOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Title, Paragraph } = Typography;

const primaryCards = [
  {
    title: '精密建模',
    description: '上传 2D 工程图纸或输入文本描述，AI 生成精密 3D CAD 模型',
    icon: <ExperimentOutlined style={{ fontSize: 40 }} />,
    path: '/generate',
    gradient: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)',
  },
  {
    title: '创意雕塑',
    description: '输入创意描述或参考图片，AI 生成自由曲面 3D 模型',
    icon: <BulbOutlined style={{ fontSize: 40 }} />,
    path: '/generate/organic',
    gradient: 'linear-gradient(135deg, #722ed1 0%, #b37feb 100%)',
  },
];

const secondaryCards = [
  {
    title: '参数化模板',
    icon: <AppstoreOutlined style={{ fontSize: 24 }} />,
    path: '/templates',
    description: '浏览预定义零件模板',
  },
  {
    title: '工程标准',
    icon: <BookOutlined style={{ fontSize: 24 }} />,
    path: '/standards',
    description: '查询行业标准规范',
  },
  {
    title: '评测基准',
    icon: <BarChartOutlined style={{ fontSize: 24 }} />,
    path: '/benchmark',
    description: '运行生成质量评测',
  },
];

export default function Home() {
  const navigate = useNavigate();

  return (
    <div>
      <Title level={2}>CAD3Dify</Title>
      <Paragraph type="secondary">
        AI 驱动的 3D 模型生成平台
      </Paragraph>

      <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
        {primaryCards.map((card) => (
          <Col key={card.path} xs={24} sm={12}>
            <Card
              hoverable
              onClick={() => navigate(card.path)}
              style={{ height: '100%', overflow: 'hidden' }}
            >
              <div
                style={{
                  background: card.gradient,
                  borderRadius: 8,
                  padding: 24,
                  marginBottom: 16,
                  textAlign: 'center',
                  color: '#fff',
                }}
              >
                {card.icon}
              </div>
              <Title level={4}>{card.title}</Title>
              <Paragraph type="secondary">{card.description}</Paragraph>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        {secondaryCards.map((card) => (
          <Col key={card.path} xs={24} sm={8}>
            <Card
              hoverable
              onClick={() => navigate(card.path)}
              style={{ textAlign: 'center', height: '100%' }}
            >
              <div style={{ marginBottom: 12, color: '#1677ff' }}>
                {card.icon}
              </div>
              <Title level={5}>{card.title}</Title>
              <Paragraph type="secondary" style={{ fontSize: 13 }}>
                {card.description}
              </Paragraph>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
